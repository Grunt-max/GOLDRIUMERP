import json
import mimetypes
import uuid
from datetime import datetime
from decimal import Decimal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .marketplaces import MarketplaceError, _coupang_headers, _json_request, _naver_token


def _price(product, channel):
    prices = [row.cost_and_price(channel)["sale_price"] for row in product.variants.filter(active=True)]
    prices = [int(value) for value in prices if value is not None]
    return min(prices) if prices else None


def _deep_merge(target, overrides):
    for key, value in (overrides or {}).items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
        else:
            target[key] = value
    return target


def publish_readiness(product, channel):
    errors = []
    setting = product.channel_settings.filter(channel=channel).first()
    if product.workspace_status != "approved": errors.append("작업 상태를 승인 완료로 변경하세요.")
    if channel not in product.target_channels: errors.append("등록 대상 채널에 추가하세요.")
    if not product.image: errors.append("대표 이미지를 등록하세요.")
    if not product.detail_page_html: errors.append("상세페이지를 작성하세요.")
    if not setting or not setting.category_code: errors.append("채널 카테고리 코드를 입력하세요.")
    if setting and setting.external_product_id: errors.append(f"이미 등록된 상품입니다: {setting.external_product_id}")
    if not _price(product, channel): errors.append("옵션 중량과 가격 기준을 입력하세요.")
    if not setting: return errors
    if channel == "coupang":
        if not setting.outbound_location_code: errors.append("쿠팡 출고지 코드를 입력하세요.")
        if not setting.return_center_code: errors.append("쿠팡 반품지 코드를 입력하세요.")
        if not setting.notice_data: errors.append("쿠팡 카테고리 고시정보를 입력하세요.")
    return errors


def _naver_upload_image(image):
    token = _naver_token()
    boundary = f"----Goldrium{uuid.uuid4().hex}"
    filename = image.name.rsplit("/", 1)[-1]
    image.open("rb")
    raw = image.read()
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"imageFiles\"; filename=\"{filename}\"\r\n"
            f"Content-Type: {content_type}\r\n\r\n").encode() + raw + f"\r\n--{boundary}--\r\n".encode()
    request = Request("https://api.commerce.naver.com/external/v1/product-images/upload", data=body, method="POST",
                      headers={"Authorization": f"Bearer {token}", "Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urlopen(request, timeout=60) as response:
            result = json.loads(response.read().decode())
    except HTTPError as exc:
        raise MarketplaceError(f"네이버 이미지 업로드 오류 {exc.code}: {exc.read().decode(errors='replace')[:800]}") from exc
    except (URLError, TimeoutError) as exc:
        raise MarketplaceError(f"네이버 이미지 업로드 연결 실패: {exc}") from exc
    images = result.get("images") or result.get("data") or []
    url = images[0].get("url") if images and isinstance(images[0], dict) else None
    if not url: raise MarketplaceError("네이버 이미지 업로드 응답에 URL이 없습니다.")
    return url


def publish_naver(product):
    setting = product.channel_settings.get(channel="naver")
    image_url = _naver_upload_image(product.image)
    price = _price(product, "naver")
    variants = list(product.variants.filter(active=True))
    option_combinations = [{"optionName1": row.get_base_variant_display(), "stockQuantity": 999,
                            "price": max(0, int(row.cost_and_price("naver")["sale_price"]) - price),
                            "sellerManagerCode": row.sku, "usable": True} for row in variants]
    origin = {
        "statusType": "WAIT", "saleType": "NEW", "leafCategoryId": setting.category_code,
        "name": setting.channel_product_name or product.name, "detailContent": product.detail_page_html,
        "images": {"representativeImage": {"url": image_url}, "optionalImages": []},
        "salePrice": price, "stockQuantity": 999,
        "deliveryInfo": {"deliveryType": "DELIVERY", "deliveryAttributeType": "NORMAL",
                         "deliveryFee": {"deliveryFeeType": setting.delivery_fee_type, "baseFee": int(setting.delivery_fee)},
                         "claimDeliveryInfo": {"returnDeliveryFee": int(setting.return_fee), "exchangeDeliveryFee": int(setting.return_fee) * 2}},
        "detailAttribute": {"optionInfo": {
                                "optionCombinationSortType": "CREATE",
                                "optionCombinationGroupNames": {"optionGroupName1": "함량 및 색상"},
                                "optionCombinations": option_combinations,
                                "useStockManagement": True,
                            },
                            "productInfoProvidedNotice": setting.notice_data},
        "customerBenefit": {},
    }
    body = {"originProduct": origin, "smartstoreChannelProduct": {"naverShoppingRegistration": True,
             "channelProductName": setting.channel_product_name or product.name}}
    _deep_merge(body, setting.extra_attributes or {})
    token = _naver_token()
    return _json_request("https://api.commerce.naver.com/external/v2/products", method="POST",
                         headers={"Authorization": f"Bearer {token}"}, body=body)


def publish_coupang(product, image_url):
    setting = product.channel_settings.get(channel="coupang")
    vendor_id = __import__("os").environ["COUPANG_VENDOR_ID"]
    now = datetime.now()
    items = []
    for row in product.variants.filter(active=True):
        sale_price = int(row.cost_and_price("coupang")["sale_price"])
        items.append({
            "itemName": row.get_base_variant_display(), "originalPrice": sale_price, "salePrice": sale_price,
            "outboundShippingTimeDay": 2, "maximumBuyCount": 999, "unitCount": 1,
            "adultOnly": "EVERYONE", "taxType": "TAX", "parallelImported": "NOT_PARALLEL_IMPORTED",
            "overseasPurchased": "NOT_OVERSEAS_PURCHASED", "pccNeeded": False,
            "externalVendorSku": row.sku,
            "images": [{"imageOrder": 0, "imageType": "REPRESENTATION", "vendorPath": image_url}],
            "notices": setting.notice_data.get("notices", []),
            "attributes": setting.notice_data.get("attributes") or [
                {"attributeTypeName": "함량 및 색상", "attributeValueName": row.get_base_variant_display(), "exposed": "EXPOSED"}
            ],
            "contents": [{"contentsType": "HTML", "contentDetails": [{"content": product.detail_page_html, "detailType": "TEXT"}]}],
            "offerCondition": "NEW",
        })
    body = {
        "displayCategoryCode": int(setting.category_code), "sellerProductName": setting.channel_product_name or product.name,
        "vendorId": vendor_id, "saleStartedAt": now.strftime("%Y-%m-%dT%H:%M:%S"),
        "saleEndedAt": "2099-12-31T23:59:59", "displayProductName": setting.channel_product_name or product.name,
        "brand": product.brand, "generalProductName": product.name, "deliveryMethod": setting.delivery_method or "SEQUENCIAL",
        "deliveryCompanyCode": setting.delivery_company_code, "deliveryChargeType": setting.delivery_fee_type,
        "deliveryCharge": int(setting.delivery_fee), "freeShipOverAmount": 0, "deliveryChargeOnReturn": int(setting.return_fee),
        "remoteAreaDeliverable": "Y", "unionDeliveryType": "UNION_DELIVERY", "returnCharge": int(setting.return_fee),
        "returnCenterCode": setting.return_center_code, "outboundShippingPlaceCode": int(setting.outbound_location_code),
        "vendorUserId": vendor_id, "requested": False, "items": items, "manufacture": product.manufacturer or product.brand,
    }
    _deep_merge(body, setting.extra_attributes or {})
    path = "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products"
    return _json_request(f"https://api-gateway.coupang.com{path}", method="POST",
                         headers=_coupang_headers("POST", path), body=body)
