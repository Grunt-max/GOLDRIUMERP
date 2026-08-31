COMMON_FIELD_ALIASES = (
    ("name", "상품명", "originProduct.name", "sellerProductName / generalProductName"),
    ("brand", "브랜드", "detailAttribute.brandName", "brand"),
    ("model_name", "모델명", "detailAttribute.modelName", "generalProductName 또는 고시정보"),
    ("manufacturer", "제조사", "productInfoProvidedNotice.jewellery.manufacturer", "notices.noticeCategoryDetailNames"),
    ("origin_country", "원산지", "detailAttribute.originAreaInfo", "items.noticeCategories"),
    ("image", "대표/추가 이미지", "originProduct.images", "items.images"),
    ("detail_page_html", "상세페이지", "detailContent", "contentDetails"),
    ("sku", "내부 옵션코드", "optionManageCode", "externalVendorSku"),
    ("weight", "중량", "option 조합 및 고시정보", "attributes / 고시정보"),
    ("sale_price", "판매가", "salePrice + option.price", "items.salePrice"),
)

CHANNEL_ONLY_FIELDS = {
    "naver": (
        "네이버 카테고리 ID", "네이버 주소록/묶음배송 설정",
        "조합형 옵션명과 옵션 추가금(판매가의 ±50% 규칙)", "네이버 이미지 업로드 API가 반환한 URL",
    ),
    "coupang": (
        "쿠팡 노출 카테고리 코드", "쿠팡 출고지·반품지 코드와 택배사 코드",
        "카테고리 메타정보가 요구하는 구매옵션 attributes", "vendorItem별 originalPrice·salePrice·재고",
    ),
}
