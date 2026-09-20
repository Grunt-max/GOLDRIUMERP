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
    """Return normalized Naver product-orders for an inclusive order-date range."""
    token = _naver_token()
    path = "/external/v1/pay-order/seller/product-orders"
    orders = []
    page = 1
    while page <= max_pages:
        query = urlencode({
            "from": f"{start_date.isoformat()}T00:00:00.000+09:00",
            "to": f"{end_date.isoformat()}T23:59:59.999+09:00",
            "rangeType": "PAYED_DATETIME", "page": page, "pageSize": 300,
        })
        result = _json_request(
            f"https://api.commerce.naver.com{path}?{query}",
            headers={"Authorization": f"Bearer {token}"},
        )
        data = result.get("data", result) if isinstance(result, dict) else []
        if isinstance(data, list):
            rows = data
        else:
            rows = data.get("contents") or data.get("content") or data.get("productOrders") or []
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
        if len(rows) < 300:
            break
        page += 1
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
