import base64
import gzip
import hashlib
import hmac
import json
import os
import time
from datetime import date, datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class MarketplaceError(Exception):
    pass


def channel_configuration():
    return {
        "naver": {
            "label": "네이버 스마트스토어",
            "configured": bool(os.environ.get("NAVER_COMMERCE_CLIENT_ID") and os.environ.get("NAVER_COMMERCE_CLIENT_SECRET")),
            "missing": [name for name in ("NAVER_COMMERCE_CLIENT_ID", "NAVER_COMMERCE_CLIENT_SECRET") if not os.environ.get(name)],
        },
        "coupang": {
            "label": "쿠팡",
            "configured": bool(os.environ.get("COUPANG_ACCESS_KEY") and os.environ.get("COUPANG_SECRET_KEY") and os.environ.get("COUPANG_VENDOR_ID")),
            "missing": [name for name in ("COUPANG_ACCESS_KEY", "COUPANG_SECRET_KEY", "COUPANG_VENDOR_ID") if not os.environ.get(name)],
        },
    }


def _json_request(url, *, method="GET", headers=None, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    for attempt in range(4):
        request = Request(url, data=data, method=method, headers={"Content-Type": "application/json", **(headers or {})})
        try:
            with urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raw_detail = exc.read()
            if exc.headers.get("Content-Encoding", "").lower() == "gzip" or raw_detail[:2] == b"\x1f\x8b":
                try:
                    raw_detail = gzip.decompress(raw_detail)
                except (OSError, EOFError):
                    pass
            detail = raw_detail.decode("utf-8", errors="replace")[:800]
            if exc.code == 429 and attempt < 3:
                retry_after = exc.headers.get("Retry-After")
                time.sleep(float(retry_after) if retry_after and retry_after.isdigit() else 2 ** attempt)
                continue
            raise MarketplaceError(f"API 오류 {exc.code}: {detail}") from exc
        except (URLError, TimeoutError) as exc:
            raise MarketplaceError(f"API 서버 연결 실패: {exc}") from exc


def _naver_token():
    try:
        import bcrypt
    except ImportError as exc:
        raise MarketplaceError("네이버 인증 모듈이 없습니다. requirements.txt를 설치해 주세요.") from exc
    client_id = os.environ["NAVER_COMMERCE_CLIENT_ID"]
    secret = os.environ["NAVER_COMMERCE_CLIENT_SECRET"]
    timestamp = str(int(time.time() * 1000))
    password = f"{client_id}_{timestamp}".encode()
    # Naver requires the bcrypt result to be encoded with standard Base64.
    signature = base64.b64encode(bcrypt.hashpw(password, secret.encode())).decode()
    payload = urlencode({
        "client_id": client_id, "timestamp": timestamp,
        "client_secret_sign": signature, "grant_type": "client_credentials", "type": "SELF",
    }).encode()
    request = Request(
        "https://api.commerce.naver.com/external/v1/oauth2/token",
        data=payload,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode())["access_token"]
    except (HTTPError, URLError, KeyError) as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:800] if isinstance(exc, HTTPError) else str(exc)
        raise MarketplaceError(f"네이버 인증 실패: {detail}") from exc


def fetch_naver_products(max_pages=20):
    token = _naver_token()
    products = []
    page = 1
    while page <= max_pages:
        result = _json_request(
            "https://api.commerce.naver.com/external/v1/products/search",
            method="POST", headers={"Authorization": f"Bearer {token}"},
            body={"page": page, "size": 100},
        )
        rows = result.get("contents") or result.get("content") or result.get("data") or []
        if isinstance(rows, dict):
            rows = rows.get("contents") or rows.get("content") or []
        products.extend(rows)
        if not rows or len(rows) < 100:
            break
        page += 1
    detailed = []
    for summary in products:
        product_id = summary.get("originProductNo") or summary.get("productNo") or summary.get("id")
        if not product_id:
            continue
        detail = _json_request(
            f"https://api.commerce.naver.com/external/v2/products/origin-products/{product_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        detail["originProductNo"] = product_id
        detail["searchProduct"] = summary
        detailed.append(detail)
        time.sleep(0.4)
    return detailed


def _coupang_headers(method, path, query=""):
    access_key = os.environ["COUPANG_ACCESS_KEY"]
    secret_key = os.environ["COUPANG_SECRET_KEY"]
    signed_date = datetime.now(timezone.utc).strftime("%y%m%dT%H%M%SZ")
    message = f"{signed_date}{method}{path}{query}"
    signature = hmac.new(secret_key.encode(), message.encode(), hashlib.sha256).hexdigest()
    return {"Authorization": f"CEA algorithm=HmacSHA256, access-key={access_key}, signed-date={signed_date}, signature={signature}"}


def fetch_coupang_products(max_pages=20):
    path = "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products"
    vendor_id = os.environ["COUPANG_VENDOR_ID"]
    products, next_token = [], None
    for _ in range(max_pages):
        params = {"vendorId": vendor_id, "maxPerPage": 100}
        if next_token:
            params["nextToken"] = next_token
        query = urlencode(params)
        result = _json_request(
            f"https://api-gateway.coupang.com{path}?{query}", headers=_coupang_headers("GET", path, query)
        )
        rows = result.get("data") or []
        products.extend(rows)
        next_token = result.get("nextToken")
        if not next_token or not rows:
            break
    detailed = []
    for summary in products:
        seller_product_id = summary.get("sellerProductId") if isinstance(summary, dict) else None
        if not seller_product_id:
            continue
        detail_path = f"{path}/{seller_product_id}"
        result = _json_request(
            f"https://api-gateway.coupang.com{detail_path}",
            headers=_coupang_headers("GET", detail_path),
        )
        detail = result.get("data") if isinstance(result, dict) else None
        if not isinstance(detail, dict):
            detail = result if isinstance(result, dict) else {}
        detail["sellerProductId"] = seller_product_id
        detail["listSummary"] = summary
        detailed.append(detail)
        time.sleep(0.15)
    return detailed


def _number(value):
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _iso_datetime(value):
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def fetch_naver_orders(start_date, end_date, max_pages=100):
    """Return Naver product-orders, splitting the requested range into API-safe days."""
    token = _naver_token()
    path = "/external/v1/pay-order/seller/product-orders"
    today = datetime.now(timezone(timedelta(hours=9))).date()
    start_date = max(start_date, today - timedelta(days=179))
    end_date = min(end_date, today)
    orders, target_date = [], start_date
    while target_date <= end_date:
        page = 1
        while page <= max_pages:
            query = urlencode({
                "from": f"{target_date.isoformat()}T00:00:00.000+09:00",
                "to": f"{target_date.isoformat()}T23:59:59.999+09:00",
                "rangeType": "PAYED_DATETIME", "page": page, "pageSize": 300,
            })
            result = _json_request(
                f"https://api.commerce.naver.com{path}?{query}",
                headers={"Authorization": f"Bearer {token}"},
            )
            data = result.get("data", result) if isinstance(result, dict) else []
            if isinstance(data, list):
                rows, has_next = data, False
            else:
                rows = data.get("contents") or data.get("content") or data.get("productOrders") or []
                pagination = data.get("pagination") or {}
                has_next = pagination.get("hasNext", len(rows) >= 300)
            for row in rows:
                order = row.get("order", {})
                product = row.get("productOrder", row)
                product_order_id = product.get("productOrderId") or row.get("productOrderId")
                ordered_at = _iso_datetime(order.get("orderDate") or product.get("orderDate"))
                if not product_order_id or not ordered_at:
                    continue
                gross = _number(product.get("totalPaymentAmount") or product.get("totalProductAmount"))
                remain = _number(product.get("remainPaymentAmount", gross))
                orders.append({
                    "external_order_id": str(order.get("orderId") or product.get("orderId") or product_order_id),
                    "external_product_order_id": str(product_order_id), "ordered_at": ordered_at,
                    "status": str(product.get("claimStatus") or product.get("productOrderStatus") or ""),
                    "product_name": str(product.get("productName") or ""),
                    "option_name": str(product.get("productOption") or ""),
                    "external_product_id": str(product.get("productId") or product.get("channelProductNo") or ""),
                    "quantity": max(1, _number(product.get("quantity"))), "gross_amount": gross,
                    "canceled_amount": max(0, gross - remain),
                    "channel_fee": _number(product.get("paymentCommission")) + _number(product.get("saleCommission")) + _number(product.get("channelCommission")),
                    "expected_settlement_amount": _number(product.get("expectedSettlementAmount")), "raw_data": row,
                })
            if not has_next:
                break
            page += 1
            time.sleep(0.55)
        target_date += timedelta(days=1)
        if target_date <= end_date:
            time.sleep(0.55)
    return orders


def fetch_coupang_orders(start_date, end_date, max_pages=100):
    """Return normalized Coupang order items, splitting the API's date window."""
    vendor_id = os.environ["COUPANG_VENDOR_ID"]
    path = f"/v2/providers/openapi/apis/api/v4/vendors/{vendor_id}/ordersheets"
    statuses = ("ACCEPT", "INSTRUCT", "DEPARTURE", "DELIVERING", "FINAL_DELIVERY", "NONE_TRACKING")
    orders, window_start = [], start_date
    while window_start <= end_date:
        window_end = min(window_start + timedelta(days=30), end_date)
        for status in statuses:
            token = None
            for _ in range(max_pages):
                params = {"createdAtFrom": window_start.isoformat(), "createdAtTo": window_end.isoformat(),
                          "status": status, "maxPerPage": 50}
                if token:
                    params["nextToken"] = token
                query = urlencode(params)
                result = _json_request(f"https://api-gateway.coupang.com{path}?{query}",
                                       headers=_coupang_headers("GET", path, query))
                data = result.get("data") or []
                rows = data if isinstance(data, list) else data.get("orders") or data.get("orderSheets") or []
                for sheet in rows:
                    order_id = sheet.get("shipmentBoxId") or sheet.get("orderId")
                    ordered_at = _iso_datetime(sheet.get("orderedAt") or sheet.get("paidAt"))
                    for item in sheet.get("orderItems", []) or []:
                        item_id = item.get("vendorItemPackageId") or item.get("vendorItemId") or item.get("sellerProductId")
                        if not order_id or not item_id or not ordered_at:
                            continue
                        gross = _number(item.get("orderPrice") or item.get("salesPrice")) * max(1, _number(item.get("shippingCount") or item.get("quantity")))
                        orders.append({
                            "external_order_id": str(order_id), "external_product_order_id": f"{order_id}-{item_id}",
                            "ordered_at": ordered_at, "status": str(sheet.get("status") or status),
                            "product_name": str(item.get("vendorItemName") or item.get("sellerProductName") or ""),
                            "option_name": str(item.get("vendorItemName") or ""), "external_product_id": str(item_id),
                            "quantity": max(1, _number(item.get("shippingCount") or item.get("quantity"))),
                            "gross_amount": gross, "canceled_amount": 0, "channel_fee": 0,
                            "expected_settlement_amount": 0, "raw_data": {"order": sheet, "item": item},
                        })
                token = result.get("nextToken") or (data.get("nextToken") if isinstance(data, dict) else None)
                if not token or not rows:
                    break
        window_start = window_end + timedelta(days=1)
    return orders


def fetch_naver_settlements(start_date, end_date):
    token = _naver_token()
    rows, window_start = [], start_date
    while window_start <= end_date:
        window_end = min(window_start + timedelta(days=30), end_date)
        page = 1
        while True:
            query = urlencode({"startDate": window_start.isoformat(), "endDate": window_end.isoformat(),
                               "page": page, "size": 1000})
            result = _json_request(
                f"https://api.commerce.naver.com/external/v1/pay-settle/settle/daily?{query}",
                headers={"Authorization": f"Bearer {token}"},
            )
            elements = result.get("elements") or []
            for item in elements:
                recognized = item.get("settleBasisEndDate") or item.get("settleBasisStartDate")
                if not recognized:
                    continue
                rows.append({
                    "external_key": f"daily-{recognized}-{item.get('merchantId', '')}-{item.get('settleMethodType', '')}",
                    "recognized_on": recognized, "settlement_on": item.get("settleExpectDate") or None,
                    "sale_type": "DAILY_SUMMARY", "external_order_id": "", "product_name": "네이버 일별 정산",
                    "option_name": "", "quantity": 0,
                    "sale_amount": abs(_number(item.get("paySettleAmount"))), "refund_amount": 0,
                    "fee_amount": abs(_number(item.get("commissionSettleAmount"))),
                    "settlement_amount": _number(item.get("settleAmount")), "raw_data": item,
                })
            pagination = result.get("pagination") or {}
            if page >= pagination.get("totalPages", 1):
                break
            page += 1
            time.sleep(0.55)
        window_start = window_end + timedelta(days=1)
        time.sleep(0.55)
    return rows + fetch_naver_settlement_cases(start_date, end_date, token=token)


def fetch_naver_settlement_cases(start_date, end_date, token=None):
    token = token or _naver_token()
    rows, target_date = [], start_date
    while target_date <= end_date:
        page = 1
        while True:
            query = urlencode({"searchDate": target_date.isoformat(),
                               "periodType": "SETTLE_CASEBYCASE_SETTLE_BASIS_DATE",
                               "page": page, "size": 1000})
            result = _json_request(
                f"https://api.commerce.naver.com/external/v1/pay-settle/settle/case?{query}",
                headers={"Authorization": f"Bearer {token}"},
            )
            for item in result.get("elements") or []:
                pay_amount = _number(item.get("paySettleAmount"))
                rows.append({
                    "external_key": f"case-{item.get('settleBasisDate')}-{item.get('productOrderId')}-{item.get('settleType')}",
                    "recognized_on": item.get("settleBasisDate"), "settlement_on": item.get("settleExpectDate") or None,
                    "sale_type": "REFUND" if pay_amount < 0 else "SALE",
                    "external_order_id": str(item.get("orderId") or ""),
                    "product_name": item.get("productName") or "", "option_name": "", "quantity": 0,
                    "sale_amount": pay_amount if pay_amount > 0 else 0,
                    "refund_amount": abs(pay_amount) if pay_amount < 0 else 0,
                    "fee_amount": abs(_number(item.get("totalPayCommissionAmount"))),
                    "settlement_amount": _number(item.get("settleExpectAmount")), "raw_data": item,
                })
            pagination = result.get("pagination") or {}
            if page >= pagination.get("totalPages", 1):
                break
            page += 1
            time.sleep(0.55)
        target_date += timedelta(days=1)
        time.sleep(0.55)
    return rows


def fetch_coupang_settlements(start_date, end_date):
    vendor_id = os.environ["COUPANG_VENDOR_ID"]
    path = "/v2/providers/openapi/apis/api/v1/revenue-history"
    rows, window_start = [], start_date
    maximum_end = min(end_date, datetime.now(timezone(timedelta(hours=9))).date() - timedelta(days=1))
    while window_start <= maximum_end:
        window_end = min(window_start + timedelta(days=29), maximum_end)
        if window_end < window_start:
            break
        token = ""
        while True:
            query = urlencode({"vendorId": vendor_id, "recognitionDateFrom": window_start.isoformat(),
                               "recognitionDateTo": window_end.isoformat(), "token": token, "maxPerPage": 50})
            result = _json_request(f"https://api-gateway.coupang.com{path}?{query}",
                                   headers=_coupang_headers("GET", path, query))
            for sale in result.get("data") or []:
                sign = -1 if sale.get("saleType") == "REFUND" else 1
                for index, item in enumerate(sale.get("items") or []):
                    amount = abs(_number(item.get("saleAmount")))
                    fee = abs(_number(item.get("serviceFee"))) + abs(_number(item.get("serviceFeeVat")))
                    settled = abs(_number(item.get("settlementAmount")))
                    rows.append({
                        "external_key": f"{sale.get('saleType')}-{sale.get('recognitionDate')}-{sale.get('orderId')}-{item.get('vendorItemId')}-{index}",
                        "recognized_on": sale.get("recognitionDate"), "settlement_on": sale.get("settlementDate") or None,
                        "sale_type": sale.get("saleType") or "SALE", "external_order_id": str(sale.get("orderId") or ""),
                        "product_name": item.get("productName") or "", "option_name": item.get("vendorItemName") or "",
                        "quantity": abs(_number(item.get("quantity"))), "sale_amount": amount if sign > 0 else 0,
                        "refund_amount": amount if sign < 0 else 0, "fee_amount": fee * sign,
                        "settlement_amount": settled * sign, "raw_data": {"sale": sale, "item": item},
                    })
            if not result.get("hasNext") or not result.get("nextToken"):
                break
            token = result["nextToken"]
            time.sleep(0.55)
        window_start = window_end + timedelta(days=1)
        time.sleep(0.55)
    return rows
