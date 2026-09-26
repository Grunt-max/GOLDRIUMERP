import json
import mimetypes
import uuid
from datetime import datetime
from decimal import Decimal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .marketplaces import MarketplaceError, _coupang_headers, _json_request, _naver_token


def _price(product, channel):
    setting = product.channel_settings.filter(channel=channel).first()
    prices = list(setting.selling_options.filter(active=True).values_list("sale_price", flat=True)) if setting else []
    prices = [int(value) for value in prices if value is not None and value > 0]
    return min(prices) if prices else None


def _active_options(setting):
    return list(setting.selling_options.filter(active=True))


def _naver_price_plan(options):
    """Translate full option prices into Naver's base price, discount and deltas."""
    if not options:
        return None
    rows = [{
        "option": option,
        "original": int(option.effective_original_price),
        "sale": int(option.sale_price),
    } for option in options]
    discounts = {row["original"] - row["sale"] for row in rows}
    if any(discount < 0 for discount in discounts):
        raise MarketplaceError("네이버 정상가는 판매가보다 낮을 수 없습니다.")
    if len(discounts) != 1:
        raise MarketplaceError(
            "네이버는 한 상품에 즉시할인액 하나를 적용합니다. "
            "모든 옵션의 '정상가 - 판매가' 금액을 같게 맞춰 주세요."
        )
    base_original = min(row["original"] for row in rows)
    discount = discounts.pop()
    return {
        "rows": rows, "base_original": base_original,
        "base_sale": base_original - discount, "discount": discount,
    }


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
    if not _price(product, channel): errors.append("이 마켓에 등록할 판매 옵션과 판매가를 입력하세요.")
    if not setting: return errors
    options = _active_options(setting)
    if any(option.effective_original_price < option.sale_price for option in options):
        errors.append("정상가는 판매가보다 낮을 수 없습니다.")
    option_groups = {(option.option_name_1, option.option_name_2) for option in options}
    if len(option_groups) > 1:
        errors.append("한 마켓 내 모든 판매 옵션의 옵션명 1·2를 같게 맞춰 주세요.")
    if channel == "naver":
        discounts = {option.effective_original_price - option.sale_price for option in options}
        if len(discounts) > 1:
            errors.append("네이버의 모든 옵션은 '정상가 - 판매가' 금액이 같아야 합니다.")
        if not setting.after_service_phone: errors.append("네이버 A/S 전화번호를 입력하세요.")
        if not setting.after_service_guide: errors.append("네이버 A/S 안내를 입력하세요.")
        if setting.origin_area_code == "04" and not setting.origin_area_content:
            errors.append("네이버 원산지를 직접 입력하세요.")
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
    options = _active_options(setting)
    price_plan = _naver_price_plan(options)
    option_combinations = []
    for row in price_plan["rows"]:
        option = row["option"]
        combination = {
            "optionName1": option.option_value_1, "stockQuantity": option.stock_quantity,
            "price": row["original"] - price_plan["base_original"],
            "sellerManagerCode": option.seller_sku, "usable": True,
        }
        if option.option_name_2 and option.option_value_2:
            combination["optionName2"] = option.option_value_2
        option_combinations.append(combination)
    group_names = {"optionGroupName1": options[0].option_name_1}
    if options[0].option_name_2:
        group_names["optionGroupName2"] = options[0].option_name_2
    origin = {
        "statusType": setting.naver_origin_status, "saleType": "NEW", "leafCategoryId": setting.category_code,
        "name": setting.channel_product_name or product.name, "detailContent": product.detail_page_html,
        "images": {"representativeImage": {"url": image_url}, "optionalImages": []},
        "salePrice": price_plan["base_original"], "stockQuantity": sum(option.stock_quantity for option in options),
        "deliveryInfo": {"deliveryType": "DELIVERY", "deliveryAttributeType": "NORMAL",
                         "deliveryFee": {"deliveryFeeType": setting.delivery_fee_type, "baseFee": int(setting.delivery_fee)},
                         "claimDeliveryInfo": {"returnDeliveryFee": int(setting.return_fee), "exchangeDeliveryFee": int(setting.return_fee) * 2}},
        "detailAttribute": {"optionInfo": {
                                "optionCombinationSortType": "CREATE",
                                "optionCombinationGroupNames": group_names,
                                "optionCombinations": option_combinations,
                                "useStockManagement": True,
                            },
                            "productInfoProvidedNotice": setting.notice_data,
                            "afterServiceInfo": {
                                "afterServiceTelephoneNumber": setting.after_service_phone,
                                "afterServiceGuideContent": setting.after_service_guide,
                            },
                            "originAreaInfo": {
                                "originAreaCode": setting.origin_area_code,
                                "content": setting.origin_area_content,
                                "plural": False,
                            },
                            "minorPurchasable": setting.minor_purchasable},
        "customerBenefit": ({"immediateDiscountPolicy": {"discountMethod": {
            "value": price_plan["discount"], "unitType": "WON",
        }}} if price_plan["discount"] else {}),
    }
    body = {"originProduct": origin, "smartstoreChannelProduct": {"naverShoppingRegistration": True,
             "channelProductName": setting.channel_product_name or product.name,
             "channelProductDisplayStatusType": setting.naver_channel_display_status}}
    _deep_merge(body, setting.extra_attributes or {})
    token = _naver_token()
    return _json_request("https://api.commerce.naver.com/external/v2/products", method="POST",
                         headers={"Authorization": f"Bearer {token}"}, body=body)


def publish_coupang(product, image_url):
    setting = product.channel_settings.get(channel="coupang")
    vendor_id = __import__("os").environ["COUPANG_VENDOR_ID"]
    now = datetime.now()
    items = []
    for option in setting.selling_options.filter(active=True):
        sale_price = int(option.sale_price)
        original_price = int(option.effective_original_price)
        option_values = [option.option_value_1] + ([option.option_value_2] if option.option_value_2 else [])
        option_attributes = [
            {"attributeTypeName": option.option_name_1, "attributeValueName": option.option_value_1, "exposed": "EXPOSED"}
        ]
        if option.option_name_2 and option.option_value_2:
            option_attributes.append({
                "attributeTypeName": option.option_name_2,
                "attributeValueName": option.option_value_2,
                "exposed": "EXPOSED",
            })
        items.append({
            "itemName": " / ".join(option_values), "originalPrice": original_price, "salePrice": sale_price,
            "outboundShippingTimeDay": 2, "maximumBuyCount": max(1, option.stock_quantity), "unitCount": 1,
            "adultOnly": "EVERYONE", "taxType": "TAX", "parallelImported": "NOT_PARALLEL_IMPORTED",
            "overseasPurchased": "NOT_OVERSEAS_PURCHASED", "pccNeeded": False,
            "externalVendorSku": option.seller_sku,
            "images": [{"imageOrder": 0, "imageType": "REPRESENTATION", "vendorPath": image_url}],
            "notices": setting.notice_data.get("notices", []),
            "attributes": setting.notice_data.get("attributes") or option_attributes,
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
