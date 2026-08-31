"""Build channel-specific drafts from the OpenMarketProduct master."""

from decimal import Decimal


DEFAULT_VARIANTS = (
    ("14KY", "14K", "Y"), ("14KP", "14K", "P"),
    ("18KY", "18K", "Y"), ("18KP", "18K", "P"),
)


def canonical_variants(product):
    saved = {variant.base_variant: variant for variant in product.variants.all() if variant.active}
    rows = []
    for code, material, market_color in DEFAULT_VARIANTS:
        variant = saved.get(code)
        rows.append({
            "code": code, "sku": variant.sku if variant else f"{product.code}-{code}",
            "material": material, "market_color": market_color,
            "weight": variant.weight if variant else None,
            "labor_price": variant.labor_cost if variant else Decimal("0"),
            "specifications": variant.specifications if variant else {},
        })
    for variant in product.variants.all():
        if variant.active and variant.base_variant == "ETC":
            rows.append({
                "code": variant.base_variant, "sku": variant.sku,
                "material": variant.specifications.get("material", "기타"),
                "market_color": variant.specifications.get("color", "기타"),
                "weight": variant.weight, "labor_price": variant.labor_cost,
                "specifications": variant.specifications,
            })
    return rows


def build_naver_draft(product):
    variants = canonical_variants(product)
    setting = next((row for row in product.channel_settings.all() if row.channel == "naver"), None)
    return {
        "channel": "naver", "strategy": "COMBINATION_OPTIONS",
        "master_code": product.code, "name": product.name,
        "option_group_names": ["함량", "색상"],
        "originProduct": {
            "name": (setting.channel_product_name if setting and setting.channel_product_name else product.name),
            "leafCategoryId": setting.category_code if setting else "",
            "detailContent": product.detail_page_html,
            "productInfoProvidedNoticeType": setting.notice_type if setting else "JEWELLERY",
        },
        "options": [{"internalSku": row["sku"], "optionName1": row["material"],
                     "optionName2": row["market_color"], "price": None, "usable": True}
                    for row in variants],
    }


def build_coupang_draft(product):
    variants = canonical_variants(product)
    setting = next((row for row in product.channel_settings.all() if row.channel == "coupang"), None)
    return {
        "channel": "coupang", "strategy": "INDEPENDENT_VENDOR_ITEMS",
        "master_code": product.code, "name": product.name,
        "sellerProductName": (setting.channel_product_name if setting and setting.channel_product_name else product.name),
        "displayCategoryCode": setting.category_code if setting else "",
        "brand": product.brand, "generalProductName": product.name,
        "deliveryMethod": setting.delivery_method if setting else "SEQUENCIAL",
        "returnCenterCode": setting.return_center_code if setting else "",
        "items": [{
            "externalVendorSku": row["sku"], "itemName": row["code"],
            "attributes": [{"name": "함량", "value": row["material"]},
                           {"name": "색상", "value": row["market_color"]}],
            "salePrice": None,
        } for row in variants],
    }


def build_channel_preview(product):
    variants = canonical_variants(product)
    listings = {row.channel: row for row in product.marketplace_snapshots.all()}
    return {
        "product": product, "variants": variants,
        "naver": build_naver_draft(product), "coupang": build_coupang_draft(product),
        "naver_listing": listings.get("naver"), "coupang_listing": listings.get("coupang"),
        "ready_for_pricing": all(row["weight"] is not None for row in variants),
        "missing_weights": [row["code"] for row in variants if row["weight"] is None],
    }
