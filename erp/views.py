from decimal import Decimal
import calendar
from datetime import date, timedelta
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from django.contrib import messages
from django.core.files.base import ContentFile
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST
from .access import master_reauthentication_required
from .gold_prices import collect_gold_prices
from .forms import CompanyProfileForm, CustomerForm, DailyActivityForm, GoldLedgerEntryForm, GoldPriceForm, MaterialForm, OpenMarketChannelSettingForm, OpenMarketProductForm, OrderForm, ProductColorForm, ProductForm, PurchaseHeaderForm, PurchaseLineFormSet, PurchaseSupplierForm, SaleHeaderForm, SaleLineFormSet
from .models import CompanyProfile, Customer, DailyActivity, DailyActivityPhoto, Factory, GoldLedgerEntry, GoldPrice, MarketplaceProduct, Material, OpenMarketChannelOffer, OpenMarketChannelSetting, OpenMarketMatchCandidate, OpenMarketProduct, OpenMarketVariant, Order, Product, ProductAlias, ProductColor, PurchaseBatch, PurchaseEntry, PurchaseSupplier, ReceivableAccount, SaleItem, SaleTransaction, generate_transaction_no
from .open_market_aliases import CHANNEL_ONLY_FIELDS, COMMON_FIELD_ALIASES
from .marketplaces import MarketplaceError, channel_configuration, fetch_coupang_products, fetch_naver_products
from .marketplace_transformers import build_channel_preview
from .product_catalog import rebuild_product_weight_profiles


def marketplace_list(request):
    return marketplace_master_products(request)


def marketplace_channel_items(request, channel):
    if channel not in {"naver", "coupang"}:
        return redirect("erp:marketplace_list")
    selected_channel = request.GET.get("channel", "")
    query = request.GET.get("q", "").strip()
    rows = MarketplaceProduct.objects.filter(channel=channel)
    if query:
        rows = rows.filter(Q(name__icontains=query) | Q(external_product_id__icontains=query))
    channels = channel_configuration()
    for key, info in channels.items():
        info["count"] = MarketplaceProduct.objects.filter(channel=key).count()
        info["last_synced"] = MarketplaceProduct.objects.filter(channel=key).order_by("-synced_at").values_list("synced_at", flat=True).first()
    return render(request, "erp/marketplace_list.html", {
        "products": Paginator(rows, 50).get_page(request.GET.get("page")),
        "channels": channels,
        "selected_channel": channel,
        "channel_key": channel,
        "channel_info": channels[channel],
        "query": query,
    })


def marketplace_master_products(request):
    products = OpenMarketProduct.objects.prefetch_related(
        "variants", "channel_settings", "marketplace_snapshots__normalized_offers"
    )
    previews = []
    for product in products:
        preview = build_channel_preview(product)
        naver = preview["naver_listing"]
        coupang = preview["coupang_listing"]
        preview["naver_offers"] = list(naver.normalized_offers.all()) if naver else []
        preview["coupang_offers"] = list(coupang.normalized_offers.all()) if coupang else []
        preview["option_count_conflict"] = bool(
            naver and coupang and naver.option_count != coupang.option_count
        )
        previews.append(preview)
    return render(request, "erp/marketplace_master_products.html", {
        "previews": previews,
    })


def marketplace_master_product_detail(request, pk):
    product = get_object_or_404(
        OpenMarketProduct.objects.prefetch_related(
            "variants", "marketplace_snapshots__normalized_offers", "channel_settings"
        ), pk=pk,
    )
    settings = {row.channel: row for row in product.channel_settings.all()}
    for channel in ("naver", "coupang"):
        if channel not in settings:
            settings[channel] = OpenMarketChannelSetting.objects.create(product=product, channel=channel)
    product_form = OpenMarketProductForm(request.POST or None, instance=product, prefix="master")
    naver_form = OpenMarketChannelSettingForm(request.POST or None, instance=settings["naver"], prefix="naver")
    coupang_form = OpenMarketChannelSettingForm(request.POST or None, instance=settings["coupang"], prefix="coupang")
    if request.method == "POST" and product_form.is_valid() and naver_form.is_valid() and coupang_form.is_valid():
        product_form.save()
        naver_form.save()
        coupang_form.save()
        messages.success(request, "오픈마켓 공통 정보와 채널별 설정을 저장했습니다.")
        return redirect("erp:marketplace_master_product_detail", pk=pk)
    preview = build_channel_preview(product)
    naver = preview["naver_listing"]
    coupang = preview["coupang_listing"]
    preview["naver_offers"] = list(naver.normalized_offers.all()) if naver else []
    preview["coupang_offers"] = list(coupang.normalized_offers.all()) if coupang else []
    preview["option_count_conflict"] = bool(naver and coupang and naver.option_count != coupang.option_count)
    pricing_rows = []
    for variant in product.variants.all():
        pricing_rows.append({"variant": variant, "naver": variant.cost_and_price("naver"),
                             "coupang": variant.cost_and_price("coupang")})
    return render(request, "erp/marketplace_master_product_detail.html", {
        "preview": preview, "product_form": product_form, "naver_form": naver_form,
        "coupang_form": coupang_form, "pricing_rows": pricing_rows,
        "field_aliases": COMMON_FIELD_ALIASES, "channel_only_fields": CHANNEL_ONLY_FIELDS,
    })


def marketplace_sales_overview(request):
    channels = channel_configuration()
    rows = []
    for key, info in channels.items():
        listings = MarketplaceProduct.objects.filter(channel=key)
        rows.append({
            "key": key, "label": info["label"], "product_count": listings.count(),
            "linked_count": listings.exclude(master_product=None).count(),
            "status": "주문·정산 API 연결 필요",
        })
    return render(request, "erp/marketplace_sales_overview.html", {"channel_rows": rows})


def marketplace_product_detail(request, pk):
    product = get_object_or_404(MarketplaceProduct, pk=pk)
    options = []
    if product.channel == "naver" and isinstance(product.raw_data, dict):
        origin = product.raw_data.get("originProduct", {})
        detail = origin.get("detailAttribute", {}) if isinstance(origin, dict) else {}
        option_info = detail.get("optionInfo", {}) if isinstance(detail, dict) else {}
        limit = product.option_price_limit
        option_sources = (
            ("optionCombinations", "조합형"), ("optionSimple", "단독형"),
            ("optionCustom", "직접입력형"), ("optionStandards", "표준형"),
            ("optionDeliveryAttributes", "배송속성"),
        )
        for source_key, type_label in option_sources:
            source_rows = option_info.get(source_key, []) if isinstance(option_info, dict) else []
            for option in source_rows if isinstance(source_rows, list) else []:
                if not isinstance(option, dict):
                    continue
                additional = product._market_decimal(option.get("price")) or Decimal("0")
                names = [str(option.get(f"optionName{number}", "")).strip() for number in range(1, 5)]
                if not any(names):
                    names = [
                        str(option.get("groupName") or option.get("optionGroupName") or "").strip(),
                        str(option.get("name") or option.get("optionName") or option.get("value") or "").strip(),
                    ]
                options.append({
                    "number": len(options) + 1, "type": type_label, "external_id": option.get("id"),
                    "name": " / ".join(name for name in names if name) or f"옵션 {len(options) + 1}",
                    "additional_price": additional,
                    "display_price": product.display_price + additional if product.display_price is not None else None,
                    "stock": option.get("stockQuantity"), "usable": option.get("usable", True),
                    "rule_ok": limit is None or abs(additional) <= limit,
                })
    elif product.channel == "coupang":
        base_price = product.display_price
        for item in product.coupang_items:
            sale_price = product._market_decimal(item.get("salePrice"))
            original_price = product._market_decimal(item.get("originalPrice"))
            attributes = item.get("attributes", []) if isinstance(item.get("attributes"), list) else []
            attribute_names = []
            for attribute in attributes:
                if not isinstance(attribute, dict):
                    continue
                type_name = str(attribute.get("attributeTypeName") or "").strip()
                value_name = str(attribute.get("attributeValueName") or "").strip()
                attribute_names.append(" ".join(value for value in (type_name, value_name) if value))
            item_name = str(item.get("itemName") or "").strip() or " / ".join(name for name in attribute_names if name) or "쿠팡 옵션"
            item_status = str(item.get("salesStatus") or item.get("saleStatus") or item.get("status") or "").upper()
            options.append({
                "number": len(options) + 1, "type": "쿠팡 아이템",
                "external_id": item.get("vendorItemId") or item.get("sellerProductItemId"),
                "name": item_name, "attributes": " / ".join(name for name in attribute_names if name),
                "additional_price": ((sale_price - base_price) if sale_price is not None and base_price is not None else Decimal("0")),
                "display_price": sale_price, "original_price": original_price,
                "stock": item.get("quantity", item.get("stockQuantity")),
                "usable": (None if not item_status else item_status not in {"STOP", "SUSPENSION", "SUSPENDED", "OUT_OF_STOCK"}),
                "status": item_status,
                "rule_ok": True,
            })
    return render(request, "erp/marketplace_product_detail.html", {
        "product": product,
        "options": options,
        "master_products": OpenMarketProduct.objects.order_by("code"),
        "suggested_code": f"MK-{product.channel[0].upper()}-{product.external_product_id}"[:40],
        "discount_amount": (
            product.sale_price - product.display_price
            if product.sale_price is not None and product.display_price is not None else None
        ),
    })


def _copy_marketplace_image(marketplace_product, master_product):
    image_url = marketplace_product.image_url
    if not image_url:
        return False
    parsed = urlparse(image_url)
    allowed_hosts = ("coupangcdn.com", "pstatic.net", "naver.net")
    hostname = parsed.hostname or ""
    if parsed.scheme != "https" or not any(hostname == host or hostname.endswith("." + host) for host in allowed_hosts):
        return False
    request = Request(image_url, headers={"User-Agent": "GoldriumERP/1.0"})
    with urlopen(request, timeout=20) as response:
        content_type = response.headers.get("Content-Type", "").split(";")[0].lower()
        extension = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}.get(content_type)
        if not extension:
            return False
        data = response.read(10 * 1024 * 1024 + 1)
        if len(data) > 10 * 1024 * 1024:
            raise ValueError("대표 이미지가 10MB를 초과합니다.")
        master_product.image.save(f"{master_product.code}{extension}", ContentFile(data), save=True)
    return True


@require_POST
def marketplace_product_import(request, pk):
    snapshot = get_object_or_404(MarketplaceProduct, pk=pk)
    action = request.POST.get("action")
    if action == "link":
        master = get_object_or_404(OpenMarketProduct, pk=request.POST.get("master_product"))
        snapshot.master_product = master
        snapshot.save(update_fields=["master_product"])
        messages.success(request, f"{snapshot.name}을(를) ERP 상품 {master.code}에 연결했습니다.")
        return redirect("erp:marketplace_product_detail", pk=pk)
    if action != "create":
        messages.error(request, "지원하지 않는 ERP 상품화 방식입니다.")
        return redirect("erp:marketplace_product_detail", pk=pk)
    code = request.POST.get("code", "").strip()[:40]
    name = request.POST.get("name", "").strip()[:120]
    if not code or not name:
        messages.error(request, "ERP 모델번호와 상품명을 입력해 주세요.")
        return redirect("erp:marketplace_product_detail", pk=pk)
    if OpenMarketProduct.objects.filter(code=code).exists():
        messages.error(request, f"이미 사용 중인 ERP 모델번호입니다: {code}")
        return redirect("erp:marketplace_product_detail", pk=pk)
    with transaction.atomic():
        master = OpenMarketProduct.objects.create(code=code, name=name, active=False)
        OpenMarketChannelSetting.objects.bulk_create([
            OpenMarketChannelSetting(product=master, channel="naver", delivery_method="DELIVERY"),
            OpenMarketChannelSetting(product=master, channel="coupang", delivery_method="SEQUENCIAL"),
        ])
        for variant_code in ("14KY", "14KP", "18KY", "18KP"):
            OpenMarketVariant.objects.create(
                product=master, sku=f"{code}-{variant_code}", base_variant=variant_code,
            )
        snapshot.master_product = master
        snapshot.save(update_fields=["master_product"])
    image_message = ""
    try:
        if _copy_marketplace_image(snapshot, master):
            image_message = " 대표 사진도 ERP에 저장했습니다."
    except Exception as exc:
        image_message = f" 사진 복사는 실패했습니다({exc})."
    messages.success(request, f"오픈마켓 마스터 초안을 생성했습니다: {master.code}.{image_message} 중량·공임 확인 후 운영 상품으로 전환하세요.")
    return redirect("erp:marketplace_product_detail", pk=pk)


def _first(data, *keys, default=""):
    for key in keys:
        value = data.get(key)
        if value is not None and value != "":
            return value
    return default


def _coupang_image_url(value):
    value = str(value or "").strip()
    if not value:
        return ""
    if value.startswith("https://image1a.coupangcdn.com/image/"):
        value = value.removeprefix("https://image1a.coupangcdn.com/image/")
    if value.startswith("//"):
        return "https:" + value
    if value.startswith(("http://", "https://")):
        return value
    return "https://thumbnail6.coupangcdn.com/thumbnails/remote/492x492ex/image/" + value.lstrip("/")


def _sync_normalized_offers(listing, channel, options):
    """Keep a channel-neutral option/price snapshot for later write APIs."""
    kept_ids = []
    base_price = listing.display_price
    for index, option in enumerate(options if isinstance(options, list) else [], start=1):
        if not isinstance(option, dict):
            continue
        if channel == "naver":
            external_id = str(option.get("id") or f"row-{index}")
            names = [str(option.get(f"optionName{number}") or "").strip() for number in range(1, 5)]
            option_name = " / ".join(value for value in names if value)
            if not option_name:
                option_name = " / ".join(str(option.get(key) or "").strip() for key in ("groupName", "name") if option.get(key))
            additional = listing._market_decimal(option.get("price")) or Decimal("0")
            original_price = listing.sale_price
            sale_price = base_price + additional if base_price is not None else None
            status = "SALE" if option.get("usable", True) else "SUSPENSION"
        else:
            external_id = str(option.get("vendorItemId") or option.get("sellerProductItemId") or f"row-{index}")
            option_name = str(option.get("itemName") or "").strip()
            original_price = listing._market_decimal(option.get("originalPrice"))
            sale_price = listing._market_decimal(option.get("salePrice"))
            additional = sale_price - base_price if sale_price is not None and base_price is not None else Decimal("0")
            status = str(option.get("salesStatus") or option.get("saleStatus") or option.get("status") or "")
        OpenMarketChannelOffer.objects.update_or_create(
            listing=listing, external_option_id=external_id,
            defaults={
                "option_name": option_name or f"옵션 {index}", "original_price": original_price,
                "sale_price": sale_price, "additional_price": additional,
                "display_price": sale_price,
                "stock_quantity": option.get("stockQuantity", option.get("quantity")),
                "sale_status": status, "raw_attributes": option,
            },
        )
        kept_ids.append(external_id)
    stale = listing.normalized_offers.all()
    if kept_ids:
        stale = stale.exclude(external_option_id__in=kept_ids)
    stale.delete()


def _sync_marketplace_rows(channel, rows):
    saved = 0
    with transaction.atomic():
        for row in rows:
            if channel == "naver":
                origin = row.get("originProduct") if isinstance(row.get("originProduct"), dict) else row
                summary = row.get("searchProduct") if isinstance(row.get("searchProduct"), dict) else row
                product_id = str(_first(row, "originProductNo", default=_first(summary, "originProductNo", "channelProductNo", "productNo", "id")))
                name = str(_first(origin, "name", "productName", "channelProductName", default=f"상품 {product_id}"))
                price = _first(origin, "salePrice", "discountedPrice", "channelProductDisplayPrice", default=None)
                status = str(_first(origin, "statusType", "channelProductStatusType"))
                category = str(_first(origin, "leafCategoryId", "categoryId"))
                url = str(_first(summary, "channelProductUrl", "productUrl"))
                images = origin.get("images") if isinstance(origin.get("images"), dict) else {}
                image = _first(images, "representativeImage", default=_first(origin, "representativeImage", "imageUrl", default=""))
                if isinstance(image, dict):
                    image = _first(image, "url", "imageUrl")
                detail_attribute = origin.get("detailAttribute") if isinstance(origin.get("detailAttribute"), dict) else {}
                option_info = detail_attribute.get("optionInfo") if isinstance(detail_attribute.get("optionInfo"), dict) else {}
                options = []
                for option_key in ("optionCombinations", "optionSimple", "optionCustom", "optionStandards"):
                    candidate = option_info.get(option_key)
                    if isinstance(candidate, list) and candidate:
                        options = candidate
                        break
            else:
                product_id = str(_first(row, "sellerProductId", "productId"))
                name = str(_first(row, "sellerProductName", "displayProductName", default=f"상품 {product_id}"))
                options = _first(row, "items", "options", default=[])
                item_prices = [
                    _first(item, "originalPrice", "salePrice", default=None)
                    for item in options if isinstance(item, dict)
                ] if isinstance(options, list) else []
                item_prices = [value for value in item_prices if value is not None]
                price = min(item_prices) if item_prices else _first(row, "salePrice", "price", default=None)
                status = str(_first(row, "statusName", "status"))
                category = str(_first(row, "displayCategoryCode", "categoryId"))
                summary = row.get("listSummary", {}) if isinstance(row.get("listSummary"), dict) else {}
                coupang_product_id = _first(summary, "productId", default=_first(row, "productId", default=""))
                url = str(_first(row, "productUrl", "url", default=(f"https://www.coupang.com/vp/products/{coupang_product_id}" if coupang_product_id else "")))
                image = _coupang_image_url(_first(row, "imageUrl", "thumbnailUrl"))
                if not image and isinstance(options, list):
                    for item in options:
                        images = item.get("images", []) if isinstance(item, dict) else []
                        if isinstance(images, list) and images:
                            candidate = images[0]
                            image = _coupang_image_url(_first(candidate, "cdnPath", "vendorPath", "url", default="")) if isinstance(candidate, dict) else ""
                            if image:
                                break
            if not product_id:
                continue
            listing, _ = MarketplaceProduct.objects.update_or_create(
                channel=channel, external_product_id=product_id,
                defaults={
                    "name": name, "status": status, "category_code": category,
                    "product_url": url, "image_url": image or "", "sale_price": price,
                    "option_count": len(options) if isinstance(options, list) else 0, "raw_data": row,
                },
            )
            _sync_normalized_offers(listing, channel, options)
            saved += 1
    return saved


@require_POST
def marketplace_sync(request, channel):
    if channel not in {"naver", "coupang"}:
        messages.error(request, "지원하지 않는 오픈마켓입니다.")
        return redirect("erp:marketplace_list")
    config = channel_configuration()[channel]
    if not config["configured"]:
        messages.error(request, f"{config['label']} API 환경설정이 없습니다: {', '.join(config['missing'])}")
        return redirect("erp:marketplace_channel_items", channel=channel)
    try:
        rows = fetch_naver_products() if channel == "naver" else fetch_coupang_products()
        saved = _sync_marketplace_rows(channel, rows)
        messages.success(request, f"{config['label']} 상품 {saved}개를 읽기 전용으로 수집했습니다.")
    except MarketplaceError as exc:
        messages.error(request, str(exc))
    return redirect("erp:marketplace_channel_items", channel=channel)


def customer_receivable_totals(sales):
    """Net a customer's sales and payments across transaction numbers."""
    rows = list(sales)
    sold_gold = sum((sale.total_pure_gold_weight for sale in rows), Decimal("0"))
    paid_gold = sum((sale.paid_gold_weight for sale in rows), Decimal("0"))
    sold_labor = sum((sale.total_labor_amount for sale in rows), Decimal("0"))
    paid_labor = sum((sale.paid_labor_amount for sale in rows), Decimal("0"))
    returned_items = SaleItem.objects.filter(transaction__in=rows, entry_type="return", is_deleted=False)
    legacy_adjustments = SaleItem.objects.filter(
        transaction__in=rows, entry_type__in=("wg", "dc", "vd"), is_deleted=False,
    )
    returned_gold = sum((item.pure_gold_weight for item in returned_items), Decimal("0"))
    returned_labor = sum((item.total_amount for item in returned_items), Decimal("0"))
    adjusted_gold = sum((item.pure_gold_weight for item in legacy_adjustments), Decimal("0"))
    adjusted_labor = sum(
        (item.total_amount for item in legacy_adjustments if item.entry_type in ("dc", "vd")),
        Decimal("0"),
    )
    return {
        "gold_receivable": sold_gold - returned_gold - paid_gold - adjusted_gold,
        "cash_receivable": Decimal("0"),
        "labor_receivable": sold_labor - returned_labor - paid_labor - adjusted_labor,
    }


def split_receivable_balance(balance):
    """Expose receivables and advances separately without changing the signed ledger balance."""
    gold = balance["gold_receivable"]
    labor = balance["labor_receivable"]
    balance.update({
        "gold_due": max(gold, Decimal("0")),
        "gold_advance": max(-gold, Decimal("0")),
        "labor_due": max(labor, Decimal("0")),
        "labor_advance": max(-labor, Decimal("0")),
    })
    return balance


def receivable_account_totals(account):
    """Return an account's opening balance plus explicitly assigned later items."""
    gold = account.opening_gold_balance
    labor = account.opening_labor_balance
    items = SaleItem.objects.exclude(transaction__status="cancel").filter(
        receivable_account=account, is_deleted=False,
    ).select_related("transaction")
    if account.opening_date:
        items = items.filter(transaction__sale_date__gt=account.opening_date)
    for item in items:
        gold_direction = Decimal("1") if item.entry_type == "sale" else Decimal("-1")
        labor_direction = Decimal("0") if item.entry_type == "wg" else gold_direction
        gold += item.pure_gold_weight * gold_direction
        labor += item.total_amount * labor_direction
    return {"gold_receivable": gold, "cash_receivable": Decimal("0"), "labor_receivable": labor}


def fulfill_matching_orders(customer, model_number, sold_quantity, completed_at=None):
    """판매 수량을 동일 거래처·모델번호의 오래된 미출고 주문부터 반영한다."""
    remaining_sale = sold_quantity
    orders = Order.objects.select_for_update().filter(
        customer=customer,
        model_number__iexact=model_number.strip(),
        source_type__in=("quick", "photo"),
        status__in=("new", "partial"),
        is_deleted=False,
    ).order_by("ordered_at", "id")
    for order in orders:
        if remaining_sale <= 0:
            break
        open_quantity = order.remaining_quantity
        if open_quantity <= 0:
            continue
        applied = min(open_quantity, remaining_sale)
        order.fulfilled_quantity += applied
        order.status = "done" if order.fulfilled_quantity >= order.quantity else "partial"
        order.completed_at = completed_at if order.status == "done" else None
        order.save(update_fields=["fulfilled_quantity", "status", "completed_at"])
        remaining_sale -= applied


def build_order_dashboard():
    groups = {"14K": {}, "18K": {}}
    open_orders = Order.objects.filter(
        status__in=("new", "partial"), is_deleted=False
    ).select_related("customer", "material")
    for order in open_orders:
        remaining = order.remaining_quantity
        material_name = order.material.name.upper() if order.material else ""
        if remaining <= 0 or material_name not in groups:
            continue
        key = (order.model_number, order.color or "-", order.delivery_type)
        row = groups[material_name].setdefault(key, {
            "material": material_name, "model_number": order.model_number,
            "color": order.color or "-", "delivery_type": order.get_delivery_type_display(),
            "remaining": Decimal("0"), "unit": order.order_unit, "order_count": 0,
        })
        row["remaining"] += remaining
        row["order_count"] += 1
    return {
        material: sorted(rows.values(), key=lambda row: (row["model_number"], row["color"], row["delivery_type"]))
        for material, rows in groups.items()
    }


def month_bounds(year, month):
    start = date(year, month, 1)
    end = date(year + (month == 12), 1 if month == 12 else month + 1, 1)
    return start, end


def monthly_sales_metrics(year, month):
    start, end = month_bounds(year, month)
    items = SaleItem.objects.filter(
        transaction__sale_date__gte=start, transaction__sale_date__lt=end,
        transaction__status__in=("new", "done"), is_deleted=False,
        entry_type__in=("sale", "return"),
    ).select_related("material")
    base_gold = Decimal("0")
    loss_gold = Decimal("0")
    labor = Decimal("0")
    for item in items:
        sign = Decimal("-1") if item.entry_type == "return" else Decimal("1")
        is_gold = bool(item.material and item.material.is_gold_material)
        base = item.total_weight * item.material.purity_rate if is_gold else Decimal("0")
        base_gold += sign * base
        if item.material and item.material.uses_loss_rate:
            loss_gold += sign * (base * item.loss_rate / Decimal("100"))
        labor += sign * item.total_amount
    purchase_base = Decimal("0")
    purchase_loss = Decimal("0")
    purchase_labor = Decimal("0")
    for item in PurchaseEntry.objects.filter(purchase_date__gte=start, purchase_date__lt=end, is_deleted=False).select_related("material"):
        base = item.actual_weight * item.material.purity_rate if item.material.is_gold_material else Decimal("0")
        if item.material.uses_loss_rate:
            purchase_loss += base * item.loss_rate / Decimal("100")
        purchase_base += base
        purchase_labor += item.purchase_amount
    return {
        "base_gold": base_gold.quantize(Decimal("0.001")),
        "loss_gold": loss_gold.quantize(Decimal("0.0001")),
        "total_gold": (base_gold + loss_gold).quantize(Decimal("0.001")),
        "labor": labor,
        "purchase_base_gold": purchase_base.quantize(Decimal("0.001")),
        "purchase_loss_gold": purchase_loss.quantize(Decimal("0.0001")),
        "purchase_labor": purchase_labor,
        "margin_base_gold": (base_gold - purchase_base).quantize(Decimal("0.001")),
        "margin_loss_gold": (loss_gold - purchase_loss).quantize(Decimal("0.0001")),
        "margin_labor": labor - purchase_labor,
    }


def monthly_customer_sales(request):
    today = timezone.localdate()
    current_month = today.replace(day=1)

    def parse_month(value):
        try:
            parsed = date.fromisoformat(f"{value}-01")
        except (TypeError, ValueError):
            return current_month
        return min(parsed, current_month)

    legacy_month = request.GET.get("month")
    start_month = parse_month(request.GET.get("start_month") or legacy_month or f"{today:%Y-%m}")
    end_month = parse_month(request.GET.get("end_month") or legacy_month or f"{today:%Y-%m}")
    if start_month > end_month:
        start_month, end_month = end_month, start_month
    start = start_month
    _, end = month_bounds(end_month.year, end_month.month)
    if end_month == current_month:
        end = today + timedelta(days=1)
    rows = {}
    items = SaleItem.objects.filter(
        transaction__sale_date__gte=start, transaction__sale_date__lt=end,
        transaction__status__in=("new", "done"), is_deleted=False,
        entry_type__in=("sale", "return"),
    ).select_related("transaction__customer", "material")
    for item in items:
        row = rows.setdefault(item.transaction.customer_id, {
            "customer": item.transaction.customer,
            "base_gold": Decimal("0"), "loss_gold": Decimal("0"),
            "total_gold": Decimal("0"), "labor": Decimal("0"), "quantity": Decimal("0"),
        })
        sign = Decimal("-1") if item.entry_type == "return" else Decimal("1")
        is_gold = bool(item.material and item.material.is_gold_material)
        base = item.total_weight * item.material.purity_rate if is_gold else Decimal("0")
        loss = base * item.loss_rate / Decimal("100") if item.material and item.material.uses_loss_rate else Decimal("0")
        row["base_gold"] += sign * base
        row["loss_gold"] += sign * loss
        row["total_gold"] += sign * (base + loss)
        row["labor"] += sign * item.total_amount
        row["quantity"] += sign * item.quantity
    sort_key = request.GET.get("sort", "total_gold")
    sort_fields = {"quantity", "base_gold", "loss_gold", "total_gold", "labor"}
    if sort_key == "customer":
        customer_rows = sorted(rows.values(), key=lambda row: row["customer"].name)
    else:
        if sort_key not in sort_fields:
            sort_key = "total_gold"
        customer_rows = sorted(rows.values(), key=lambda row: (row[sort_key], row["customer"].name), reverse=True)
    totals = {
        key: sum((row[key] for row in customer_rows), Decimal("0"))
        for key in ("base_gold", "loss_gold", "total_gold", "labor", "quantity")
    }
    latest_wholesale = GoldPrice.objects.filter(market_type="wholesale").first()
    wholesale_per_gram = latest_wholesale.applied_price_per_gram if latest_wholesale else None
    if wholesale_per_gram is not None:
        for row in customer_rows:
            row["loss_value"] = (row["loss_gold"] * wholesale_per_gram).quantize(Decimal("1"))
        totals["loss_value"] = (totals["loss_gold"] * wholesale_per_gram).quantize(Decimal("1"))
    else:
        totals["loss_value"] = None
    return render(request, "erp/monthly_customer_sales.html", {
        "rows": customer_rows, "totals": totals,
        "start_month": start_month, "end_month": end_month,
        "start_month_text": f"{start_month:%Y-%m}", "end_month_text": f"{end_month:%Y-%m}",
        "current_month_text": f"{current_month:%Y-%m}",
        "period_start": start, "period_end": end - timedelta(days=1),
        "selected_sort": sort_key, "wholesale_price": latest_wholesale,
    })


def activity_calendar(year, month):
    start, end = month_bounds(year, month)
    activity_map = {}
    for activity in DailyActivity.objects.filter(
        activity_date__gte=start, activity_date__lt=end, is_deleted=False
    ).select_related("created_by").prefetch_related("photos"):
        activity_map.setdefault(activity.activity_date, []).append(activity)
    sale_counts = {}
    payment_counts = {}
    shipment_counts = {}
    order_counts = {}
    gold_counts = {}
    for sale in SaleTransaction.objects.filter(
        sale_date__gte=start, sale_date__lt=end, status__in=("new", "done"),
        items__entry_type__in=("sale", "return"), items__is_deleted=False,
    ).distinct():
        sale_counts[sale.sale_date] = sale_counts.get(sale.sale_date, 0) + 1
    for payment in SaleItem.objects.filter(
        transaction__sale_date__gte=start, transaction__sale_date__lt=end,
        transaction__status__in=("new", "done"), entry_type="payment", is_deleted=False,
    ).select_related("transaction"):
        day = payment.transaction.sale_date
        payment_counts[day] = payment_counts.get(day, 0) + 1
    for order in Order.objects.filter(completed_at__gte=start, completed_at__lt=end, status="done", is_deleted=False):
        shipment_counts[order.completed_at] = shipment_counts.get(order.completed_at, 0) + 1
    for order in Order.objects.filter(ordered_at__gte=start, ordered_at__lt=end, is_deleted=False).exclude(status="cancel"):
        order_counts[order.ordered_at] = order_counts.get(order.ordered_at, 0) + 1
    for entry in GoldLedgerEntry.objects.filter(entry_date__gte=start, entry_date__lt=end, is_deleted=False):
        gold_counts[entry.entry_date] = gold_counts.get(entry.entry_date, 0) + 1
    weeks = []
    for week in calendar.Calendar(firstweekday=6).monthdatescalendar(year, month):
        weeks.append([{
            "date": day, "in_month": day.month == month, "is_today": day == timezone.localdate(),
            "activities": activity_map.get(day, []), "sale_count": sale_counts.get(day, 0),
            "payment_count": payment_counts.get(day, 0), "shipment_count": shipment_counts.get(day, 0),
            "order_count": order_counts.get(day, 0),
            "gold_count": gold_counts.get(day, 0),
        } for day in week])
    return weeks


def dashboard(request):
    today = timezone.localdate()
    month_start, next_month_start = month_bounds(today.year, today.month)
    sales = SaleTransaction.objects.exclude(status="cancel")
    total_sales = sum((sale.total_labor_amount for sale in sales), Decimal("0"))
    customer_sales = {}
    for sale in sales:
        customer_sales.setdefault(sale.customer_id, []).append(sale)
    customer_balances = [
        split_receivable_balance(customer_receivable_totals(rows))
        for rows in customer_sales.values()
    ]
    total_gold_receivable = sum((row["gold_due"] for row in customer_balances), Decimal("0"))
    total_labor_receivable = sum((row["labor_due"] for row in customer_balances), Decimal("0"))
    total_gold_advance = sum((row["gold_advance"] for row in customer_balances), Decimal("0"))
    total_labor_advance = sum((row["labor_advance"] for row in customer_balances), Decimal("0"))
    overdue_groups = {}
    overdue_orders = Order.objects.filter(
        status__in=("new", "partial"), is_deleted=False,
        due_date__lt=timezone.localdate(),
    ).select_related("customer").order_by("due_date", "customer__name")
    for order in overdue_orders:
        group = overdue_groups.setdefault(order.customer_id, {
            "customer": order.customer, "count": 0, "oldest_due_date": order.due_date,
        })
        group["count"] += 1
        if order.due_date < group["oldest_due_date"]:
            group["oldest_due_date"] = order.due_date
    def market_price_context(market_type):
        prices = list(GoldPrice.objects.filter(market_type=market_type)[:2])
        latest = prices[0] if prices else None
        previous = prices[1] if len(prices) > 1 else None
        change = rate = None
        if latest and previous:
            change = latest.applied_price_per_gram - previous.applied_price_per_gram
            if previous.applied_price_per_gram:
                rate = change / previous.applied_price_per_gram * Decimal("100")
        return {"latest": latest, "change": change, "change_rate": rate}
    retail_price = market_price_context("retail")
    wholesale_price = market_price_context("wholesale")
    collected_times = [
        price["latest"].collected_at
        for price in (retail_price, wholesale_price)
        if price["latest"] and price["latest"].collected_at
    ]
    gold_last_collected = max(collected_times) if collected_times else None
    month_metrics = monthly_sales_metrics(today.year, today.month)
    wholesale_loss_value = None
    if wholesale_price["latest"]:
        wholesale_loss_value = (
            month_metrics["loss_gold"] * wholesale_price["latest"].applied_price_per_gram
        ).quantize(Decimal("1"))
    return render(request, "erp/dashboard.html", {
        "order_count": sales.count(), "total_sales": total_sales,
        "total_gold_receivable": total_gold_receivable,
        "total_labor_receivable": total_labor_receivable,
        "total_gold_advance": total_gold_advance,
        "total_labor_advance": total_labor_advance,
        "recent_payments": SaleItem.objects.filter(
            entry_type="payment", is_deleted=False,
            transaction__status__in=("new", "done"),
        ).select_related("transaction", "transaction__customer").order_by(
            "-transaction__sale_date", "-transaction_id", "-id"
        )[:8],
        "order_dashboard": build_order_dashboard(),
        "overdue_customers": list(overdue_groups.values()),
        "month_metrics": month_metrics,
        "wholesale_loss_value": wholesale_loss_value,
        "month_start": month_start, "month_end": next_month_start - timedelta(days=1),
        "calendar_weeks": activity_calendar(today.year, today.month),
        "calendar_year": today.year, "calendar_month": today.month,
        "activity_form": DailyActivityForm(),
        "customers": Customer.objects.order_by("name"),
        "today": today,
        "retail_price": retail_price, "wholesale_price": wholesale_price,
        "gold_last_collected": gold_last_collected,
        "gold_price_form": GoldPriceForm(initial={"market_type": "retail", "price_date": today, "application_rate": Decimal("102.00")}),
    })


@require_POST
def gold_price_save(request):
    instance = GoldPrice.objects.filter(
        market_type=request.POST.get("market_type"), price_date=request.POST.get("price_date")
    ).first()
    form = GoldPriceForm(request.POST, instance=instance)
    if form.is_valid():
        price = form.save(commit=False)
        if request.user.is_authenticated:
            price.created_by = request.user
        price.collected_at = timezone.now()
        price.save()
        messages.success(request, f"{price.price_date:%Y-%m-%d} 금시세를 저장했습니다.")
    else:
        messages.error(request, "금시세 입력값을 확인하세요.")
    return redirect("erp:dashboard")


@require_POST
def gold_price_refresh(request):
    try:
        retail, wholesale = collect_gold_prices()
        messages.success(
            request,
            f"시세 갱신 완료: 소매 {retail.applied_price_per_gram:,.0f}원/g · "
            f"도매 {wholesale.applied_price_per_gram:,.0f}원/g",
        )
    except Exception as exc:
        messages.error(request, f"시세 갱신 실패: {exc} 마지막 정상 시세를 유지합니다.")
    return redirect(request.POST.get("next") or "erp:gold_price_list")


def _gold_chart(market_type, dates):
    rows = list(GoldPrice.objects.filter(
        market_type=market_type, price_date__in=dates,
    ).order_by("price_date"))
    if not rows:
        return {"rows": [], "points": "", "point_rows": [], "minimum": 0, "maximum": 0}
    values = [int(row.applied_price_per_gram) for row in rows]
    minimum, maximum = min(values), max(values)
    spread = maximum - minimum or 1
    count = len(rows) - 1
    point_rows = []
    for index, (row, value) in enumerate(zip(rows, values)):
        x = 400 if count == 0 else 30 + index * 740 / count
        y = 165 - (value - minimum) * 120 / spread
        point_rows.append({"row": row, "x": f"{x:.1f}", "y": f"{y:.1f}", "price": value})
    points = " ".join(f"{point['x']},{point['y']}" for point in point_rows)
    return {
        "rows": list(reversed(rows)), "points": points, "point_rows": point_rows,
        "minimum": minimum, "maximum": maximum,
        "first_date": rows[0].price_date, "last_date": rows[-1].price_date,
    }


def gold_price_list(request):
    price_dates = list(
        GoldPrice.objects.order_by("-price_date").values_list("price_date", flat=True).distinct()
    )
    page_obj = Paginator(price_dates, 10).get_page(request.GET.get("page"))
    page_dates = list(page_obj.object_list)
    return render(request, "erp/gold_price_list.html", {
        "retail_chart": _gold_chart("retail", page_dates),
        "wholesale_chart": _gold_chart("wholesale", page_dates),
        "latest_retail": GoldPrice.objects.filter(market_type="retail").first(),
        "latest_wholesale": GoldPrice.objects.filter(market_type="wholesale").first(),
        "page_obj": page_obj,
        "page_range": page_obj.paginator.get_elided_page_range(page_obj.number, on_each_side=2, on_ends=1),
    })


def daily_activity_list(request):
    today = timezone.localdate()
    month_text = request.GET.get("month", f"{today:%Y-%m}")
    try:
        selected_month = date.fromisoformat(f"{month_text}-01")
    except ValueError:
        selected_month = today.replace(day=1)
    selected_date = parse_date(request.GET.get("date", "")) or today
    day_activities = DailyActivity.objects.filter(
        activity_date=selected_date, is_deleted=False
    ).select_related("created_by").prefetch_related("photos")
    customer_sales = {}
    day_items = SaleItem.objects.filter(
        transaction__sale_date=selected_date,
        transaction__status__in=("new", "done"), is_deleted=False,
        entry_type__in=("sale", "return", "payment"),
    ).select_related("transaction__customer")
    for item in day_items:
        customer = item.transaction.customer
        row = customer_sales.setdefault(customer.pk, {
            "customer": customer, "sale_gold": Decimal("0"), "sale_labor": Decimal("0"),
            "payment_gold": Decimal("0"), "payment_labor": Decimal("0"),
        })
        if item.entry_type == "payment":
            row["payment_gold"] += item.pure_gold_weight
            row["payment_labor"] += item.total_amount
        else:
            sign = Decimal("-1") if item.entry_type == "return" else Decimal("1")
            row["sale_gold"] += sign * item.pure_gold_weight
            row["sale_labor"] += sign * item.total_amount
    day_shipments = Order.objects.filter(
        completed_at=selected_date, status="done", is_deleted=False
    ).select_related("customer", "material")
    day_orders = Order.objects.filter(
        ordered_at=selected_date, is_deleted=False
    ).exclude(status="cancel").select_related("customer", "material")
    day_gold_entries = GoldLedgerEntry.objects.filter(
        entry_date=selected_date, is_deleted=False
    ).select_related("factory", "material", "purchase_supplier")
    return render(request, "erp/daily_activity_list.html", {
        "calendar_weeks": activity_calendar(selected_month.year, selected_month.month),
        "calendar_year": selected_month.year, "calendar_month": selected_month.month,
        "selected_date": selected_date, "day_activities": day_activities,
        "day_customer_sales": sorted(customer_sales.values(), key=lambda row: row["customer"].name),
        "day_shipments": day_shipments,
        "day_orders": day_orders,
        "day_gold_entries": day_gold_entries,
        "activity_form": DailyActivityForm(initial={"activity_date": selected_date}),
    })


@require_POST
def daily_activity_create(request):
    form = DailyActivityForm(request.POST, request.FILES)
    if form.is_valid():
        activity = form.save(commit=False)
        if request.user.is_authenticated:
            activity.created_by = request.user
        activity.save()
        for image in form.cleaned_data.get("images", []):
            DailyActivityPhoto.objects.create(activity=activity, image=image)
        messages.success(request, "당일 행적을 등록했습니다.")
    else:
        messages.error(request, "행적 날짜와 업무 내용을 확인하세요.")
    if request.POST.get("return_to") == "activity_list":
        activity_date = request.POST.get("activity_date", "")
        return redirect(f"{request.path.replace('/new/', '/')}?date={activity_date}&month={activity_date[:7]}")
    return redirect("erp:dashboard")


@require_POST
def daily_activity_delete(request, pk):
    activity = get_object_or_404(DailyActivity, pk=pk, is_deleted=False)
    activity.is_deleted = True
    activity.deleted_at = timezone.now()
    activity.save(update_fields=["is_deleted", "deleted_at"])
    messages.success(request, "당일 행적을 삭제 처리했습니다.")
    return redirect(f"/activities/?date={activity.activity_date}&month={activity.activity_date:%Y-%m}")


def gold_ledger_list(request):
    today = timezone.localdate()
    latest_issue = GoldLedgerEntry.objects.filter(is_deleted=False, entry_type="issue").order_by("-entry_date", "-id").first()
    default_start = str(latest_issue.entry_date) if latest_issue else ""
    start_date = request.GET.get("start_date") or default_start
    end_date = request.GET.get("end_date") or str(today)
    entry_type = request.GET.get("entry_type", "")
    include_all_data = request.GET.get("include_all_data") == "1"
    start = parse_date(start_date)
    end = parse_date(end_date)
    closing = GoldLedgerEntry.objects.filter(is_deleted=False, is_closing_transfer=True).order_by("-entry_date", "-id").first()
    ledger_start = closing.entry_date + timedelta(days=1) if closing else None
    effective_start = start if include_all_data else max(filter(None, [start, ledger_start]), default=None)

    manual = GoldLedgerEntry.objects.filter(is_deleted=False).select_related("material", "created_by", "purchase_supplier")
    payments = SaleItem.objects.filter(entry_type="payment", is_deleted=False).exclude(transaction__status="cancel").select_related("transaction__customer", "material")
    purchases = PurchaseEntry.objects.filter(is_deleted=False).select_related("supplier", "material")
    if effective_start:
        manual = manual.filter(entry_date__gte=effective_start)
        payments = payments.filter(transaction__sale_date__gte=effective_start)
        purchases = purchases.filter(purchase_date__gte=effective_start)
    if end:
        manual, payments, purchases = manual.filter(entry_date__lte=end), payments.filter(transaction__sale_date__lte=end), purchases.filter(purchase_date__lte=end)
    rows = []
    for item in manual.filter(entry_type__in=("issue", "adjustment")):
        row_type = "supplier_issue" if item.entry_type == "issue" and item.destination_type == "purchase_supplier" else "own_factory_issue" if item.entry_type == "issue" else "adjustment"
        destination = item.purchase_supplier.name if item.purchase_supplier_id else item.factory.name
        rows.append({"date": item.entry_date, "type": row_type, "type_label": "매입처 금 불출" if row_type == "supplier_issue" else "우리공장 금 불출" if row_type == "own_factory_issue" else "재고 조정", "material": item.material, "actual": item.actual_weight, "pure": item.pure_gold_weight, "effect": item.gold_balance_effect, "source": item.reference_no, "memo": f"{destination} · {item.memo}" if item.memo else destination, "image": item.image, "manual": item})
    for item in payments:
        rows.append({"date": item.transaction.sale_date, "type": "customer_payment", "type_label": "거래처 금 결제", "material": item.material, "actual": item.weight, "pure": item.pure_gold_weight, "effect": item.pure_gold_weight, "source": item.transaction.transaction_no, "memo": item.transaction.customer.name, "image": None, "manual": None})
    if entry_type:
        rows = [row for row in rows if row["type"] == entry_type]
    rows.sort(key=lambda row: (row["date"], row["source"] or ""), reverse=True)
    summary = {"customer_payment": Decimal("0"), "own_factory_issue": Decimal("0"), "supplier_issue": Decimal("0"), "purchase_pure": Decimal("0"), "purchase_loss": Decimal("0"), "balance_effect": Decimal("0")}
    for row in rows:
        if row["type"] in summary:
            summary[row["type"]] += row["pure"]
        summary["balance_effect"] += row["effect"]
    for item in purchases:
        base_pure = (item.actual_weight * item.material.purity_rate).quantize(Decimal("0.001"))
        summary["purchase_pure"] += item.pure_gold_weight
        summary["purchase_loss"] += item.pure_gold_weight - base_pure

    all_manual = GoldLedgerEntry.objects.filter(is_deleted=False, entry_type__in=("issue", "adjustment"))
    all_payments = SaleItem.objects.filter(entry_type="payment", is_deleted=False).exclude(transaction__status="cancel")
    if ledger_start:
        all_manual = all_manual.filter(entry_date__gte=ledger_start)
        all_payments = all_payments.filter(transaction__sale_date__gte=ledger_start)
    current_balance = sum((item.gold_balance_effect for item in all_manual), Decimal("0")) + sum((item.pure_gold_weight for item in all_payments), Decimal("0"))
    return render(request, "erp/gold_ledger_list.html", {
        "entries": rows, "summary": summary, "current_balance": current_balance,
        "entry_types": [("customer_payment", "거래처 금 결제"), ("own_factory_issue", "우리공장 금 불출"), ("supplier_issue", "매입처 금 불출"), ("adjustment", "재고 조정")],
        "start_date": start_date, "end_date": end_date, "selected_entry_type": entry_type,
        "include_all_data": include_all_data, "ledger_cutoff": closing.entry_date if closing else None,
        "entry_form": GoldLedgerEntryForm(),
    })


@require_POST
def gold_ledger_create(request):
    form = GoldLedgerEntryForm(request.POST, request.FILES)
    if form.is_valid():
        entry = form.save(commit=False)
        entry.factory, _ = Factory.objects.get_or_create(name="우리공장")
        if request.user.is_authenticated:
            entry.created_by = request.user
        entry.save()
        messages.success(request, "금 수불 내역을 등록했습니다.")
    else:
        messages.error(request, "수불 구분·재질·중량을 확인하세요.")
    return redirect("erp:gold_ledger_list")


def purchase_list(request):
    today = timezone.localdate()
    start_date = request.GET.get("start_date") or str(today.replace(day=1))
    end_date = request.GET.get("end_date") or str(today)
    supplier_id = request.GET.get("supplier", "")
    entries = PurchaseEntry.objects.filter(is_deleted=False).select_related("supplier", "material", "batch")
    if parse_date(start_date): entries = entries.filter(purchase_date__gte=start_date)
    if parse_date(end_date): entries = entries.filter(purchase_date__lte=end_date)
    if supplier_id.isdigit(): entries = entries.filter(supplier_id=supplier_id)
    rows = list(entries)
    return render(request, "erp/purchase_list.html", {"entries": rows, "start_date": start_date, "end_date": end_date, "selected_supplier": supplier_id, "suppliers": PurchaseSupplier.objects.filter(active=True), "total_actual": sum((x.actual_weight for x in rows), Decimal("0")), "total_pure": sum((x.pure_gold_weight for x in rows), Decimal("0")), "total_amount": sum((x.purchase_amount for x in rows), Decimal("0")), "supplier_form": PurchaseSupplierForm()})


@require_POST
def purchase_supplier_create(request):
    form = PurchaseSupplierForm(request.POST)
    if form.is_valid(): form.save(); messages.success(request, "매입처를 등록했습니다.")
    else: messages.error(request, "매입처 정보를 확인하세요.")
    return redirect("erp:purchase_list")


def purchase_create(request):
    header_form = PurchaseHeaderForm(request.POST or None, request.FILES or None, prefix="header")
    line_formset = PurchaseLineFormSet(request.POST or None, request.FILES or None, prefix="lines")
    if request.method == "POST" and header_form.is_valid() and line_formset.is_valid():
        purchase_date = header_form.cleaned_data["purchase_date"]
        supplier = header_form.cleaned_data["supplier"]
        reference_no = header_form.cleaned_data.get("reference_no", "").strip()
        slip_image = header_form.cleaned_data.get("image")
        with transaction.atomic():
            if not reference_no:
                daily_count = PurchaseBatch.objects.filter(purchase_date=purchase_date).count() + 1
                reference_no = f"P{purchase_date:%y%m%d}{daily_count:03d}"
            batch = PurchaseBatch.objects.create(purchase_date=purchase_date, supplier=supplier, reference_no=reference_no, image=slip_image, created_by=request.user if request.user.is_authenticated else None)
            saved = 0
            for line in line_formset:
                data = line.cleaned_data
                if data.get("DELETE") or not data.get("material") or not data.get("actual_weight"):
                    continue
                entry = line.save(commit=False)
                entry.batch, entry.purchase_date, entry.supplier, entry.reference_no = batch, purchase_date, supplier, reference_no
                if data.get("loss_rate") is None:
                    entry.loss_rate = supplier.default_loss_rate if supplier.default_loss_rate is not None else entry.material.default_loss_rate
                if request.user.is_authenticated:
                    entry.created_by = request.user
                entry.save()
                saved += 1
        messages.success(request, f"매입번호 {reference_no}로 {saved}개 품목을 등록했습니다.")
        return redirect("erp:purchase_list")
    if request.method == "POST":
        messages.error(request, "매입처와 입력 행의 재질·중량을 확인하세요.")
    material_defaults = [{"id": material.pk, "purity_rate": str(material.purity_rate), "loss_rate": str(material.default_loss_rate), "apply_loss_rate": material.apply_loss_rate} for material in Material.objects.filter(active=True)]
    supplier_defaults = [{"id": supplier.pk, "loss_rate": str(supplier.default_loss_rate) if supplier.default_loss_rate is not None else None} for supplier in PurchaseSupplier.objects.filter(active=True)]
    return render(request, "erp/purchase_form.html", {"header_form": header_form, "line_formset": line_formset, "material_defaults": material_defaults, "supplier_defaults": supplier_defaults})


@require_POST
def purchase_delete(request, pk):
    entry = get_object_or_404(PurchaseEntry, pk=pk, is_deleted=False)
    entry.is_deleted, entry.deleted_at = True, timezone.now()
    entry.save(update_fields=["is_deleted", "deleted_at"])
    messages.success(request, "매입 내역을 삭제 처리했습니다.")
    return redirect("erp:purchase_list")


@require_POST
def gold_ledger_delete(request, pk):
    entry = get_object_or_404(GoldLedgerEntry, pk=pk, is_deleted=False)
    entry.is_deleted = True
    entry.deleted_at = timezone.now()
    entry.save(update_fields=["is_deleted", "deleted_at"])
    messages.success(request, "금 수불 내역을 삭제 처리했습니다.")
    return redirect("erp:gold_ledger_list")


def order_list(request):
    order_dashboard = build_order_dashboard()
    orders = Order.objects.filter(is_deleted=False).select_related("customer", "product", "material")
    start_date = request.GET.get("start_date", "")
    end_date = request.GET.get("end_date") or str(timezone.localdate())
    status = request.GET.get("status", "")
    include_completed = request.GET.get("include_completed") == "1"
    customer_id = request.GET.get("customer", "")
    query = request.GET.get("q", "").strip()
    page_size = request.GET.get("page_size", "10")
    if page_size not in {"10", "30", "50", "100"}:
        page_size = "10"
    date_type = request.GET.get("date_type", "completed" if status == "done" else "ordered")
    date_field = "completed_at" if date_type == "completed" else "ordered_at"
    if parse_date(start_date):
        orders = orders.filter(**{f"{date_field}__gte": start_date})
    if parse_date(end_date):
        orders = orders.filter(**{f"{date_field}__lte": end_date})
    if not include_completed and status != "done":
        orders = orders.exclude(status="done")
    if status in {"new", "partial", "done", "cancel"}:
        orders = orders.filter(status=status)
    if customer_id.isdigit():
        orders = orders.filter(customer_id=customer_id)
    if query:
        orders = orders.filter(Q(customer__name__icontains=query) | Q(model_number__icontains=query) | Q(raw_order_text__icontains=query) | Q(memo__icontains=query))
    result_count = orders.count()
    page_obj = Paginator(orders, int(page_size)).get_page(request.GET.get("page"))
    return render(request, "erp/order_list.html", {
        "orders": page_obj, "page_obj": page_obj, "result_count": result_count,
        "order_dashboard": order_dashboard,
        "customers": Customer.objects.filter(customer_type="sales"),
        "start_date": start_date, "end_date": end_date, "selected_status": status,
        "selected_customer": customer_id, "query": query, "date_type": date_type,
        "include_completed": include_completed,
        "today": timezone.localdate(), "page_size": page_size,
        "create_form": OrderForm(),
        "products": Product.objects.filter(active=True).only("code", "name"),
    })


def order_customer_outstanding(request):
    """거래처별 미출고 주문을 팝업에서 조회한다."""
    grouped = {}
    orders = Order.objects.filter(status__in=("new", "partial"), is_deleted=False).select_related(
        "customer", "material"
    ).order_by("customer__name", "due_date", "ordered_at", "id")
    for order in orders:
        remaining = order.remaining_quantity
        if remaining <= 0:
            continue
        group = grouped.setdefault(order.customer_id, {
            "customer": order.customer, "items": [],
            "semi_remaining": Decimal("0"), "finished_remaining": Decimal("0"),
        })
        group["items"].append(order)
        if order.delivery_type == "semi":
            group["semi_remaining"] += remaining
        else:
            group["finished_remaining"] += remaining
    return render(request, "erp/order_customer_outstanding.html", {
        "customer_groups": list(grouped.values()),
        "today": timezone.localdate(),
    })


def order_create(request):
    form = OrderForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        parsed_lines = form.cleaned_data.get("parsed_lines") or []
        if parsed_lines:
            image_name = None
            with transaction.atomic():
                for index, parsed in enumerate(parsed_lines):
                    product = Product.objects.filter(code__iexact=parsed["model_number"], active=True).first()
                    # Explicit text such as "18kw" must not be overwritten by a
                    # catalog product whose default material happens to be 14K.
                    material = parsed["material"]
                    loss_rate = (
                        product.default_loss_rate if product and product.default_loss_rate is not None
                        else form.cleaned_data["customer"].default_loss_rate
                        if form.cleaned_data["customer"].default_loss_rate is not None
                        else material.default_loss_rate
                    )
                    order = Order(
                        customer=form.cleaned_data["customer"], product=product,
                        model_number=parsed["model_number"], material=material,
                        weight=product.default_weight or 0 if product else 0,
                        unit_price=product.unit_price if product else 0,
                        loss_rate=loss_rate or 0, quantity=parsed["quantity"],
                        status=form.cleaned_data["status"], ordered_at=form.cleaned_data["ordered_at"],
                        due_date=form.cleaned_data["due_date"], source_type=form.cleaned_data["source_type"],
                        raw_order_text=form.cleaned_data["raw_order_text"], color=parsed["color"],
                        delivery_type=parsed["delivery_type"], length_spec=parsed["length_spec"],
                        option_detail=(parsed["option_detail"] or form.cleaned_data.get("option_detail") or "") if parsed["delivery_type"] == "finished" else "",
                        memo=form.cleaned_data.get("memo") or "",
                    )
                    if index == 0 and form.cleaned_data.get("order_image"):
                        order.order_image = form.cleaned_data["order_image"]
                    elif image_name:
                        order.order_image = image_name
                    order.save()
                    image_name = order.order_image.name or image_name
            messages.success(request, f"빠른 주문 {len(parsed_lines)}건을 등록했습니다.")
        else:
            form.save()
            messages.success(request, "주문 1건을 등록했습니다.")
        if request.POST.get("next") == "dashboard":
            return redirect("erp:dashboard")
        return redirect("erp:order_list")
    return render(request, "erp/form.html", {"form": form, "title": "주문 등록", "description": "거래처와 상품, 금액을 입력합니다."})


@require_POST
def order_complete(request, pk):
    order = get_object_or_404(Order, pk=pk, is_deleted=False)
    order.fulfilled_quantity = order.quantity
    order.status = "done"
    order.completed_at = timezone.localdate()
    order.save(update_fields=["fulfilled_quantity", "status", "completed_at"])
    messages.success(request, f"주문 품목 {order.model_number}을(를) 완료 처리했습니다.")
    return redirect("erp:order_list")


def order_edit(request, pk):
    order = get_object_or_404(Order, pk=pk, is_deleted=False)
    form = OrderForm(request.POST or None, request.FILES or None, instance=order)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"주문 {order.transaction_no}을(를) 수정했습니다.")
        return redirect("erp:order_list")
    return render(request, "erp/form.html", {
        "form": form, "title": "주문 수정", "description": f"주문번호 {order.transaction_no}",
    })


@require_POST
def order_bulk_action(request):
    order_ids = [value for value in request.POST.getlist("order_ids") if value.isdigit()]
    action = request.POST.get("action")
    orders = Order.objects.filter(pk__in=order_ids, is_deleted=False)
    if not order_ids:
        messages.error(request, "처리할 주문을 선택하세요.")
    elif action == "delete":
        count = orders.update(is_deleted=True, deleted_at=timezone.now())
        messages.success(request, f"주문 {count}건을 삭제 처리했습니다.")
    elif action == "cancel":
        count = orders.update(status="cancel", completed_at=None)
        messages.success(request, f"주문 {count}건을 취소 처리했습니다.")
    else:
        messages.error(request, "올바른 처리 방법을 선택하세요.")
    return redirect("erp:order_list")


def sale_create(request):
    selected_customer = None
    if request.method == "GET" and request.GET.get("customer", "").isdigit():
        selected_customer = Customer.objects.filter(
            pk=request.GET["customer"], customer_type="sales",
        ).first()
    header_form = SaleHeaderForm(
        request.POST or None,
        prefix="header",
        initial={"customer": selected_customer.pk} if selected_customer else None,
    )
    line_formset = SaleLineFormSet(request.POST or None, prefix="lines")
    if request.method == "POST" and header_form.is_valid() and line_formset.is_valid():
        lines = [form.cleaned_data for form in line_formset if form.cleaned_data.get("model_number") and not form.cleaned_data.get("DELETE")]
        customer = header_form.cleaned_data["customer"]
        sale_date = header_form.cleaned_data["ordered_at"]
        current_has_payment = any(line["entry_type"] == "payment" for line in lines)
        first_sale_after_payment_date = sale_date if current_has_payment else None
        if not current_has_payment:
            latest_payment = (
                SaleItem.objects.filter(
                    transaction__customer=customer, transaction__status__in=("new", "done"),
                    transaction__sale_date__lte=sale_date, entry_type="payment", is_deleted=False,
                ).select_related("transaction")
                .order_by("-transaction__sale_date", "-transaction_id", "-id").first()
            )
            if latest_payment:
                later_sale_exists = SaleItem.objects.filter(
                    transaction__customer=customer, transaction__status__in=("new", "done"),
                    transaction__sale_date__lte=sale_date, entry_type="sale", is_deleted=False,
                ).filter(
                    Q(transaction__sale_date__gt=latest_payment.transaction.sale_date)
                    | Q(transaction__sale_date=latest_payment.transaction.sale_date, transaction_id__gt=latest_payment.transaction_id)
                ).exists()
                if not later_sale_exists:
                    first_sale_after_payment_date = latest_payment.transaction.sale_date
        first_sale_note_applied = False
        for line in lines:
            if line.get("loss_rate") is None:
                product = line.get("catalog_product")
                if product and product.default_loss_rate is not None:
                    line["loss_rate"] = product.default_loss_rate
                elif customer.default_loss_rate is not None:
                    line["loss_rate"] = customer.default_loss_rate
                else:
                    line["loss_rate"] = line["material"].default_loss_rate
            if not line.get("memo"):
                if line["entry_type"] == "payment":
                    line["memo"] = f"결제일: {sale_date:%Y-%m-%d}"
                elif line["entry_type"] == "sale" and first_sale_after_payment_date and not first_sale_note_applied:
                    line["memo"] = f"직전 결제일: {first_sale_after_payment_date:%Y-%m-%d}"
                    first_sale_note_applied = True
        if not header_form.errors:
            with transaction.atomic():
                sale = SaleTransaction.objects.create(
                    transaction_no=generate_transaction_no(header_form.cleaned_data["ordered_at"]),
                    customer=header_form.cleaned_data["customer"], sale_date=header_form.cleaned_data["ordered_at"],
                    status=header_form.cleaned_data["status"], memo=header_form.cleaned_data.get("memo", ""),
                )
                for line in lines:
                    item = SaleItem.objects.create(
                        transaction=sale, entry_type=line["entry_type"], product=line.get("catalog_product"), model_number=line["model_number"].strip(),
                        receivable_account=header_form.cleaned_data.get("receivable_account"),
                        material=line["material"], color=line.get("color"), weight=line["weight"],
                        settlement_weight=line.get("settlement_weight"), loss_rate=line.get("loss_rate") or 0,
                        quantity=line["quantity"], unit_price=line["unit_price"],
                        labor_amount=0, memo=line.get("memo") or "",
                    )
                    if item.entry_type == "sale":
                        fulfill_matching_orders(sale.customer, item.model_number, item.quantity, sale.sale_date)
                sale.refresh_totals()
            messages.success(request, f"정상 반영되었습니다. 거래번호 {sale.transaction_no} · {len(lines)}건")
            if request.POST.get("_popup") == "1":
                return render(request, "erp/sale_saved.html", {"sale": sale})
            return redirect("erp:sales_list")
    product_defaults = [{
        "id": product.id, "model_number": product.code, "name": product.name,
        "material_id": None, "color_id": None, "weight": "",
        "unit_price": str(product.unit_price), "loss_rate": None,
        "image_url": product.image.url if product.image else "",
        "aliases": list(product.aliases.values_list("alias", flat=True)),
        "weight_profiles": [{
            "material_id": profile.material_id, "color_id": profile.color_id,
            "weight": str(profile.average_weight), "sale_samples": profile.sale_sample_count,
            "purchase_samples": profile.purchase_sample_count,
        } for profile in product.weight_profiles.all()],
    } for product in Product.objects.filter(active=True).prefetch_related("aliases", "weight_profiles")]
    material_defaults = [{
        "id": material.id, "name": material.name, "loss_rate": str(material.default_loss_rate),
        "purity_rate": str(material.purity_rate), "apply_loss_rate": material.apply_loss_rate,
        "payment_material": material.name.strip().upper() == "24K",
    } for material in Material.objects.filter(active=True)]
    return render(request, "erp/sale_form.html", {
        "header_form": header_form, "line_formset": line_formset,
        "submission_failed": request.method == "POST",
        "product_defaults": product_defaults, "material_defaults": material_defaults,
        "customer_defaults": list(Customer.objects.filter(customer_type="sales").values("id", "name")),
        "receivable_accounts": list(ReceivableAccount.objects.filter(
            active=True, customer__receivable_accounts_enabled=True,
        ).values("id", "customer_id", "name")),
    })


def receivables_list(request):
    rows = {}
    active_accounts = list(ReceivableAccount.objects.filter(
        active=True, customer__receivable_accounts_enabled=True,
    ).select_related("customer"))
    customer_cutoffs = {}
    for account in active_accounts:
        rows[(account.customer_id, account.pk)] = {
            "customer": account.customer, "account": account, "transaction_ids": set(),
            "gold_receivable": account.opening_gold_balance,
            "labor_receivable": account.opening_labor_balance,
            "recent_transaction_date": account.opening_date, "recent_payment_date": None,
        }
        if account.opening_date:
            customer_cutoffs[account.customer_id] = max(
                filter(None, [customer_cutoffs.get(account.customer_id), account.opening_date])
            )
    items = SaleItem.objects.exclude(transaction__status="cancel").filter(is_deleted=False).select_related(
        "transaction", "transaction__customer", "receivable_account",
    )
    for item in items:
        if item.receivable_account and item.receivable_account.opening_date and item.transaction.sale_date <= item.receivable_account.opening_date:
            continue
        if not item.receivable_account_id and customer_cutoffs.get(item.transaction.customer_id) and item.transaction.sale_date <= customer_cutoffs[item.transaction.customer_id]:
            continue
        key = (item.transaction.customer_id, item.receivable_account_id)
        row = rows.setdefault(key, {
            "customer": item.transaction.customer,
            "account": item.receivable_account,
            "transaction_ids": set(), "gold_receivable": Decimal("0"), "labor_receivable": Decimal("0"),
            "recent_transaction_date": None, "recent_payment_date": None,
        })
        row["transaction_ids"].add(item.transaction_id)
        gold_direction = Decimal("1") if item.entry_type == "sale" else Decimal("-1")
        labor_direction = gold_direction
        if item.entry_type == "wg":
            labor_direction = Decimal("0")
        row["gold_receivable"] += item.pure_gold_weight * gold_direction
        row["labor_receivable"] += item.total_amount * labor_direction
        row["recent_transaction_date"] = max(filter(None, [row["recent_transaction_date"], item.transaction.sale_date]))
        if item.entry_type == "payment":
            row["recent_payment_date"] = max(filter(None, [row["recent_payment_date"], item.transaction.sale_date]))
    for row in rows.values():
        row["transactions"] = len(row.pop("transaction_ids"))
        split_receivable_balance(row)
    receivables = sorted(
        (
            row for row in rows.values()
            if row["gold_receivable"] != 0 or row["labor_receivable"] != 0
        ),
        key=lambda row: (row["customer"].name, row["account"].name if row["account"] else ""),
    )
    receivable_rows = [row for row in receivables if row["gold_due"] or row["labor_due"]]
    advance_rows = [row for row in receivables if row["gold_advance"] or row["labor_advance"]]
    totals = {
        key: sum((row[key] for row in receivables), Decimal("0"))
        for key in ("gold_due", "gold_advance", "labor_due", "labor_advance")
    }
    return render(request, "erp/receivables_list.html", {
        "receivables": receivables,
        "receivable_rows": receivable_rows,
        "advance_rows": advance_rows,
        "totals": totals,
    })


def customer_sales_summary(request, pk):
    customer = get_object_or_404(Customer, pk=pk, customer_type="sales")
    sales = SaleTransaction.objects.exclude(status="cancel").filter(customer=customer)
    account_id = request.GET.get("account", "")
    account = None
    if account_id.isdigit():
        account = get_object_or_404(ReceivableAccount, pk=account_id, customer=customer, active=True)
    balances = receivable_account_totals(account) if account else customer_receivable_totals(sales)
    recent_transaction_date = sales.order_by("-sale_date", "-id").values_list("sale_date", flat=True).first()
    recent_payment_date = sales.filter(items__entry_type="payment").order_by("-sale_date", "-id").values_list("sale_date", flat=True).first()
    return JsonResponse({
        "customer_id": customer.pk,
        "account_name": account.name if account else None,
        "default_loss_rate": str(customer.default_loss_rate) if customer.default_loss_rate is not None else None,
        "gold_receivable": str(balances["gold_receivable"]),
        "labor_receivable": str(balances["labor_receivable"]),
        "recent_transaction_date": recent_transaction_date.isoformat() if recent_transaction_date else None,
        "recent_payment_date": recent_payment_date.isoformat() if recent_payment_date else None,
    })


def customer_sales_history(request, pk):
    customer = get_object_or_404(Customer, pk=pk, customer_type="sales")
    selected_date = parse_date(request.GET.get("date", "")) or timezone.localdate()
    items = SaleItem.objects.exclude(transaction__status="cancel").filter(
        transaction__customer=customer,
        transaction__sale_date__lte=selected_date,
        is_deleted=False,
    ).select_related("transaction", "material").order_by(
        "-transaction__sale_date", "-transaction_id", "-id",
    )[:8]
    return JsonResponse({"results": [{
        "date": item.transaction.sale_date.strftime("%y-%m-%d"),
        "transaction_no": item.transaction.transaction_no,
        "entry_type": item.get_entry_type_display(),
        "model_number": item.model_number,
        "material": item.material.name if item.material else "-",
        "weight": str(item.total_weight),
        "pure_weight": str(item.pure_gold_weight),
        "quantity": item.quantity,
        "labor": str(item.total_amount),
        "memo": item.memo,
    } for item in items]})


def customer_ledger(request, pk):
    customer = get_object_or_404(Customer, pk=pk, customer_type="sales")
    today = timezone.localdate()
    start_date = parse_date(request.GET.get("start_date", "")) or (today - timedelta(days=30))
    end_date = parse_date(request.GET.get("end_date", "")) or today
    if start_date > end_date:
        start_date, end_date = end_date, start_date
    items = SaleItem.objects.exclude(transaction__status="cancel").filter(
        transaction__customer=customer,
        is_deleted=False,
    ).select_related("transaction", "material").order_by("transaction__sale_date", "transaction_id", "id")
    selected_account = request.GET.get("account", "")
    account = None
    if selected_account.isdigit():
        account = get_object_or_404(ReceivableAccount, pk=selected_account, customer=customer)
        items = items.filter(receivable_account=account)
    elif selected_account == "default":
        items = items.filter(receivable_account__isnull=True)
    gold_balance = account.opening_gold_balance if account else Decimal("0")
    labor_balance = account.opening_labor_balance if account else Decimal("0")
    if account and account.opening_date:
        items = items.filter(transaction__sale_date__gt=account.opening_date)
    ledger = []
    for item in items:
        direction = Decimal("1") if item.entry_type == "sale" else Decimal("-1")
        gold_delta = item.pure_gold_weight * direction
        labor_delta = item.total_amount * direction
        gold_balance += gold_delta
        labor_balance += labor_delta
        if start_date <= item.transaction.sale_date <= end_date:
            ledger.append({
                "item": item, "gold_delta": gold_delta, "labor_delta": labor_delta,
                "gold_balance": gold_balance, "labor_balance": labor_balance,
            })
    return render(request, "erp/customer_ledger.html", {
        "customer": customer, "account": account, "selected_account": selected_account, "ledger": reversed(ledger),
        "opening_date": account.opening_date if account else None,
        "opening_gold_balance": account.opening_gold_balance if account else Decimal("0"),
        "opening_labor_balance": account.opening_labor_balance if account else Decimal("0"),
        "gold_balance": gold_balance, "labor_balance": labor_balance,
        "start_date": start_date.isoformat(), "end_date": end_date.isoformat(),
    })


def product_search(request):
    query = request.GET.get("q", "").strip()
    products = Product.objects.filter(active=True)
    if query:
        products = products.filter(Q(code__icontains=query) | Q(name__icontains=query))
    alias_ids = ProductAlias.objects.filter(alias__icontains=query).values_list("product_id", flat=True) if query else []
    if query:
        products = Product.objects.filter(Q(pk__in=alias_ids) | Q(code__icontains=query) | Q(name__icontains=query), active=True)
    products = products.prefetch_related("aliases", "weight_profiles")[:20]
    return JsonResponse({"results": [{
        "id": product.id, "model_number": product.code, "name": product.name,
        "material_id": None, "material": "", "color_id": None, "color": "",
        "weight": "", "unit_price": str(product.unit_price), "loss_rate": None,
        "image_url": product.image.url if product.image else "",
        "aliases": list(product.aliases.values_list("alias", flat=True)),
        "weight_profiles": [{"material_id": p.material_id, "color_id": p.color_id, "weight": str(p.average_weight)} for p in product.weight_profiles.all()],
    } for product in products]})


def sales_list(request):
    items = SaleItem.objects.exclude(transaction__status="cancel").select_related("transaction__customer", "product", "material", "color")
    today_date = timezone.localdate()
    if "start_date" not in request.GET and "end_date" not in request.GET:
        display_date = (
            items.filter(is_deleted=False)
            .order_by("-transaction__sale_date")
            .values_list("transaction__sale_date", flat=True)
            .first()
        ) or today_date
        if items.filter(is_deleted=False, transaction__sale_date=today_date).exists():
            display_date = today_date
        start_date = end_date = display_date.isoformat()
    else:
        start_date = request.GET.get("start_date", "")
        end_date = request.GET.get("end_date", "")
    customer_id = request.GET.get("customer", "")
    material_id = request.GET.get("material", "")
    status = request.GET.get("status", "")
    query = request.GET.get("q", "").strip()
    sort = request.GET.get("sort", "latest")
    page_size = request.GET.get("page_size", "30")
    include_deleted = request.GET.get("include_deleted") == "1"
    if parse_date(start_date):
        items = items.filter(transaction__sale_date__gte=start_date)
    if parse_date(end_date):
        items = items.filter(transaction__sale_date__lte=end_date)
    if customer_id.isdigit():
        items = items.filter(transaction__customer_id=customer_id)
    if material_id.isdigit():
        items = items.filter(material_id=material_id)
    if status in {"sale", "return", "payment"}:
        items = items.filter(entry_type=status)
    if query:
        search = Q(transaction__customer__name__icontains=query) | Q(product__name__icontains=query) | Q(model_number__icontains=query) | Q(transaction__transaction_no__icontains=query) | Q(memo__icontains=query)
        if query.isdigit():
            search |= Q(transaction_id=int(query))
        items = items.filter(search)

    ordering = {
        "latest": ("-transaction__sale_date", "-transaction_id", "id"),
        "oldest": ("transaction__sale_date", "transaction_id", "id"),
        "customer": ("transaction__customer__name", "-transaction__sale_date"),
        "amount": ("-unit_price", "-transaction__sale_date"),
    }
    items = items.order_by(*ordering.get(sort, ordering["latest"]))

    display_orders = list(items if include_deleted else items.filter(is_deleted=False))
    summary_orders = list(items.filter(is_deleted=False))
    seen_transactions = set()
    for item in display_orders:
        item.is_transaction_first = item.transaction_id not in seen_transactions
        seen_transactions.add(item.transaction_id)
    transaction_ids = {item.transaction_id for item in summary_orders}
    summary_transactions = list(SaleTransaction.objects.filter(id__in=transaction_ids))
    total_sales = sum((item.total_amount for item in summary_orders), Decimal("0"))
    total_paid = sum((sale.paid_labor_amount for sale in summary_transactions), Decimal("0"))
    total_unpaid = sum((sale.labor_receivable for sale in summary_transactions), Decimal("0"))
    total_quantity = sum((order.quantity for order in summary_orders), 0)
    total_weight = sum((order.total_weight for order in summary_orders), Decimal("0"))
    total_pure_weight = sum((order.pure_gold_weight for order in summary_orders), Decimal("0"))
    total_gold_receivable = sum((sale.gold_receivable for sale in summary_transactions), Decimal("0"))
    total_labor = sum((sale.total_labor_amount for sale in summary_transactions), Decimal("0"))
    total_paid_labor = sum((sale.paid_labor_amount for sale in summary_transactions), Decimal("0"))
    total_unpaid_labor = sum((sale.labor_receivable for sale in summary_transactions), Decimal("0"))
    entry_type_summary = {
        "sale": {
            "label": "판매", "quantity": sum((item.quantity for item in summary_orders if item.entry_type == "sale"), 0),
            "weight": sum((item.total_weight for item in summary_orders if item.entry_type == "sale"), Decimal("0")),
            "pure_weight": sum((item.pure_gold_weight for item in summary_orders if item.entry_type == "sale"), Decimal("0")),
            "labor": sum((item.total_amount for item in summary_orders if item.entry_type == "sale"), Decimal("0")),
        },
        "payment": {
            "label": "결제", "quantity": sum((item.quantity for item in summary_orders if item.entry_type == "payment"), 0),
            "weight": sum((item.total_weight for item in summary_orders if item.entry_type == "payment"), Decimal("0")),
            "pure_weight": sum((item.pure_gold_weight for item in summary_orders if item.entry_type == "payment"), Decimal("0")),
            "labor": sum((item.total_amount for item in summary_orders if item.entry_type == "payment"), Decimal("0")),
        },
        "return": {
            "label": "반품", "quantity": sum((item.quantity for item in summary_orders if item.entry_type == "return"), 0),
            "weight": sum((item.total_weight for item in summary_orders if item.entry_type == "return"), Decimal("0")),
            "pure_weight": sum((item.pure_gold_weight for item in summary_orders if item.entry_type == "return"), Decimal("0")),
            "labor": sum((item.total_amount for item in summary_orders if item.entry_type == "return"), Decimal("0")),
        },
    }
    net_sales_pure = entry_type_summary["sale"]["pure_weight"] - entry_type_summary["return"]["pure_weight"]
    net_sales_labor = entry_type_summary["sale"]["labor"] - entry_type_summary["return"]["labor"]
    receivable_pure = net_sales_pure - entry_type_summary["payment"]["pure_weight"]
    receivable_labor = net_sales_labor - entry_type_summary["payment"]["labor"]
    material_totals = {}
    for order in summary_orders:
        if order.entry_type == "payment":
            continue
        direction = Decimal("1") if order.entry_type == "sale" else Decimal("-1")
        name = order.material.name if order.material else "미지정"
        row = material_totals.setdefault(name, {"name": name, "pure_weight": Decimal("0"), "labor": Decimal("0")})
        row["pure_weight"] += order.pure_gold_weight * direction
        row["labor"] += order.total_amount * direction
    material_total_pure_weight = sum((row["pure_weight"] for row in material_totals.values()), Decimal("0"))
    material_total_labor = sum((row["labor"] for row in material_totals.values()), Decimal("0"))
    if page_size not in {"30", "50", "100"}:
        page_size = "30"
    page_obj = Paginator(display_orders, int(page_size)).get_page(request.GET.get("page"))
    page_query_params = request.GET.copy()
    page_query_params.pop("page", None)
    return render(request, "erp/sales_list.html", {
        "items": page_obj.object_list, "page_obj": page_obj,
        "customers": Customer.objects.filter(customer_type="sales"), "materials": Material.objects.filter(active=True),
        "start_date": start_date, "end_date": end_date, "selected_customer": customer_id,
        "selected_material": material_id, "selected_status": status, "query": query, "selected_sort": sort, "page_size": page_size,
        "total_sales": total_sales, "total_paid": total_paid, "total_unpaid": total_unpaid,
        "total_quantity": total_quantity, "total_weight": total_weight, "total_pure_weight": total_pure_weight,
        "total_gold_receivable": total_gold_receivable,
        "total_labor": total_labor, "total_paid_labor": total_paid_labor, "total_unpaid_labor": total_unpaid_labor,
        "material_summary": material_totals.values(), "result_count": len(display_orders),
        "material_total_pure_weight": material_total_pure_weight, "material_total_labor": material_total_labor,
        "net_sales_pure": net_sales_pure, "net_sales_labor": net_sales_labor,
        "receivable_pure": receivable_pure, "receivable_labor": receivable_labor,
        "entry_type_summary": entry_type_summary.values(), "include_deleted": include_deleted,
        "page_range": page_obj.paginator.get_elided_page_range(page_obj.number, on_each_side=2, on_ends=1),
        "page_query": page_query_params.urlencode(),
    })


def sale_transaction_detail(request, pk):
    sale = get_object_or_404(
        SaleTransaction.objects.select_related("customer"), pk=pk
    )
    items = list(
        sale.items.filter(is_deleted=False)
        .select_related("product", "material", "color")
        .order_by("id")
    )
    image_products = Product.objects.exclude(image="").prefetch_related("aliases")
    image_by_model = {}
    for product in image_products:
        image_by_model[product.code.strip().casefold()] = product.image
        for alias in product.aliases.all():
            image_by_model[alias.alias.strip().casefold()] = product.image
    for item in items:
        item.statement_image = (
            item.product.image
            if item.product_id and item.product.image
            else image_by_model.get(item.model_number.strip().casefold())
        )
    prior_sales = SaleTransaction.objects.exclude(status="cancel").filter(customer=sale.customer).filter(
        Q(sale_date__lt=sale.sale_date) | Q(sale_date=sale.sale_date, id__lt=sale.id)
    )
    prior = customer_receivable_totals(prior_sales)
    to_don = lambda value: (Decimal(value) / Decimal("3.75")).quantize(Decimal("0.001"))
    current = {
        entry_type: {
            "gold": sum((item.pure_gold_weight for item in items if item.entry_type == entry_type), Decimal("0")),
            "labor": sum((item.total_amount for item in items if item.entry_type == entry_type), Decimal("0")),
            "quantity": sum((item.quantity for item in items if item.entry_type == entry_type), 0),
        }
        for entry_type in ("sale", "return", "payment")
    }
    for row in current.values():
        row["don"] = to_don(row["gold"])
    after = {
        "gold_receivable": prior["gold_receivable"] + current["sale"]["gold"] - current["return"]["gold"] - current["payment"]["gold"],
        "labor_receivable": prior["labor_receivable"] + current["sale"]["labor"] - current["return"]["labor"] - current["payment"]["labor"],
    }
    prior["gold_don"] = to_don(prior["gold_receivable"])
    after["gold_don"] = to_don(after["gold_receivable"])
    recent_payment_item = (
        SaleItem.objects.filter(transaction__in=prior_sales, entry_type="payment", is_deleted=False)
        .select_related("transaction").order_by("-transaction__sale_date", "-transaction_id", "-id").first()
    )
    if recent_payment_item:
        recent_payment_items = SaleItem.objects.filter(
            transaction=recent_payment_item.transaction, entry_type="payment", is_deleted=False
        )
        recent_payment = {
            "date": recent_payment_item.transaction.sale_date,
            "gold": sum((item.pure_gold_weight for item in recent_payment_items), Decimal("0")),
            "labor": sum((item.total_amount for item in recent_payment_items), Decimal("0")),
        }
    else:
        recent_payment = {"date": None, "gold": Decimal("0"), "labor": Decimal("0")}
    recent_payment["don"] = to_don(recent_payment["gold"])
    net_current = {
        "gold": current["sale"]["gold"] - current["return"]["gold"],
        "quantity": current["sale"]["quantity"] - current["return"]["quantity"],
        "labor": current["sale"]["labor"] - current["return"]["labor"],
    }
    material_net_weights = {}
    for material_name in ("14K", "18K", "24K"):
        sold_weight = sum((item.total_weight for item in items if item.entry_type == "sale" and item.material and item.material.name.upper() == material_name), Decimal("0"))
        returned_weight = sum((item.total_weight for item in items if item.entry_type == "return" and item.material and item.material.name.upper() == material_name), Decimal("0"))
        material_net_weights[material_name] = sold_weight - returned_weight
    company_profile = CompanyProfile.objects.first() or CompanyProfile()
    return render(request, "erp/sale_transaction_detail.html", {
        "sale": sale,
        "items": items,
        "empty_rows": range(max(0, 10 - len(items))),
        "copies": (1, 2),
        "prior": prior,
        "current": current,
        "after": after,
        "recent_payment": recent_payment,
        "net_current": net_current,
        "material_net_weights": material_net_weights,
        "company_profile": company_profile,
        "statement_supplier_name": sale.customer.supplier_name_override or company_profile.supplier_name,
    })


def normalized_posted_ids(values):
    """Return integer IDs even if display localization inserted thousands separators."""
    normalized = []
    for value in values:
        compact = str(value).replace(",", "").strip()
        if compact.isdigit():
            normalized.append(int(compact))
    return normalized


@require_POST
def sales_soft_delete(request):
    item_ids = normalized_posted_ids(request.POST.getlist("order_ids"))
    items = list(SaleItem.objects.filter(id__in=item_ids, is_deleted=False).select_related("transaction"))
    if not items:
        messages.error(request, "삭제할 판매 품목을 선택하세요.")
        return redirect("erp:sales_list")
    transactions = {item.transaction for item in items}
    with transaction.atomic():
        SaleItem.objects.filter(id__in=[item.id for item in items]).update(is_deleted=True)
        for sale in transactions:
            sale.refresh_totals()
    messages.success(request, f"선택한 판매 품목 {len(items)}건을 삭제 처리했습니다.")
    return redirect("erp:sales_list")


@require_POST
def sales_return(request):
    item_ids = normalized_posted_ids(request.POST.getlist("order_ids"))
    sale_items = list(
        SaleItem.objects.filter(
            id__in=item_ids, is_deleted=False, entry_type="sale",
            transaction__status__in=("new", "done"),
        ).select_related("transaction", "transaction__customer")
    )
    already_returned_ids = set(
        SaleItem.objects.filter(
            returned_from_id__in=[item.id for item in sale_items],
            entry_type="return", is_deleted=False,
        ).exclude(transaction__status="cancel").values_list("returned_from_id", flat=True)
    )
    eligible_items = [item for item in sale_items if item.id not in already_returned_ids]
    if not eligible_items:
        messages.error(request, "반품 가능한 판매 품목을 선택하세요. 결제·반품·삭제 품목이나 이미 반품된 품목은 처리할 수 없습니다.")
        return redirect("erp:sales_list")

    return_date = timezone.localdate()
    transactions_by_customer = {}
    with transaction.atomic():
        for original in eligible_items:
            return_transaction = transactions_by_customer.get(original.transaction.customer_id)
            if return_transaction is None:
                return_transaction = SaleTransaction.objects.create(
                    transaction_no=generate_transaction_no(return_date),
                    customer=original.transaction.customer,
                    sale_date=return_date,
                    status="new",
                    memo="체크 품목 반품",
                )
                transactions_by_customer[original.transaction.customer_id] = return_transaction
            reference = f"원거래 {original.transaction.transaction_no}"
            memo = f"{reference} / {original.memo}" if original.memo else reference
            SaleItem.objects.create(
                transaction=return_transaction,
                entry_type="return",
                receivable_account=original.receivable_account,
                model_number=original.model_number,
                product=original.product,
                material=original.material,
                color=original.color,
                weight=original.weight,
                settlement_weight=original.settlement_weight,
                quantity=original.quantity,
                sales_unit=original.sales_unit,
                loss_rate=original.loss_rate,
                unit_price=original.unit_price,
                labor_amount=original.labor_amount,
                labor_total_override=original.labor_total_override,
                memo=memo[:200],
                purchase_supplier=original.purchase_supplier,
                purchase_loss_rate=original.purchase_loss_rate,
                purchase_labor_amount=original.purchase_labor_amount,
                returned_from=original,
            )
        for return_transaction in transactions_by_customer.values():
            return_transaction.refresh_totals()

    skipped = len(item_ids) - len(eligible_items)
    message = f"판매 품목 {len(eligible_items)}건을 반품 처리했습니다."
    if skipped > 0:
        message += f" 처리할 수 없는 선택 {skipped}건은 제외했습니다."
    messages.success(request, message)
    return redirect("erp:sales_list")


@require_POST
def sales_merge(request):
    item_ids = normalized_posted_ids(request.POST.getlist("order_ids"))
    items = list(SaleItem.objects.select_related("transaction").filter(id__in=item_ids, is_deleted=False))
    if len(items) < 2:
        messages.error(request, "통합할 판매 품목을 2개 이상 선택하세요.")
        return redirect("erp:sales_list")
    transactions = {item.transaction for item in items}
    if len({sale.customer_id for sale in transactions}) != 1:
        messages.error(request, "같은 거래처의 판매만 통합할 수 있습니다.")
        return redirect("erp:sales_list")
    if any(sale.items.filter(is_deleted=False).exclude(id__in=item_ids).exists() for sale in transactions):
        messages.error(request, "거래번호 통합은 해당 거래의 모든 품목을 선택해야 합니다.")
        return redirect("erp:sales_list")
    with transaction.atomic():
        target = min(transactions, key=lambda sale: sale.id)
        for source in transactions - {target}:
            target.paid_gold_weight += source.paid_gold_weight
            target.paid_cash_amount += source.paid_cash_amount
            target.paid_labor_amount += source.paid_labor_amount
            source.items.update(transaction=target)
            source.delete()
        target.save()
        target.refresh_totals()
    messages.success(request, f"선택 품목을 거래번호 {target.transaction_no}로 통합했습니다.")
    return redirect("erp:sale_transaction_detail", pk=target.pk)


@require_POST
def sales_split(request):
    item_ids = normalized_posted_ids(request.POST.getlist("order_ids"))
    items = list(SaleItem.objects.select_related("transaction").filter(id__in=item_ids, is_deleted=False))
    if not items:
        messages.error(request, "분리할 판매 품목을 선택하세요.")
        return redirect("erp:sales_list")
    if any(item.transaction.paid_gold_weight or item.transaction.paid_cash_amount or item.transaction.paid_labor_amount for item in items):
        messages.error(request, "결제 내역이 있는 거래는 결제 배분 문제로 분리할 수 없습니다.")
        return redirect("erp:sales_list")
    with transaction.atomic():
        affected = {item.transaction for item in items}
        for item in items:
            original = item.transaction
            split_sale = SaleTransaction.objects.create(transaction_no=generate_transaction_no(original.sale_date), customer=original.customer, sale_date=original.sale_date, status=original.status, memo=original.memo)
            item.transaction = split_sale
            item.save(update_fields=["transaction"])
            split_sale.refresh_totals()
        for sale in affected:
            if sale.items.exists(): sale.refresh_totals()
            else: sale.delete()
    messages.success(request, f"선택한 {len(items)}개 품목을 각각 새 거래번호로 분리했습니다.")
    return redirect("erp:sales_list")


def customer_list(request):
    query = request.GET.get("q", "").strip()
    customers = Customer.objects.all()
    if query:
        customers = customers.filter(name__icontains=query)
    return render(request, "erp/customer_list.html", {"customers": customers, "query": query, "create_form": CustomerForm()})


def customer_lookup(request):
    query = request.GET.get("q", "").strip()
    target = request.GET.get("target", "sale")
    customers = Customer.objects.filter(customer_type="sales")
    if query:
        customers = customers.filter(
            Q(name__icontains=query) | Q(contact__icontains=query) |
            Q(phone__icontains=query) | Q(aliases__alias__icontains=query)
        ).distinct()
    return render(request, "erp/customer_lookup.html", {
        "customers": customers[:100], "query": query, "target": target,
    })


def customer_create(request):
    form = CustomerForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("erp:customer_list")
    return render(request, "erp/form.html", {"form": form, "title": "거래처 등록", "description": "거래처 기본 연락처를 등록합니다."})


def customer_edit(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    form = CustomerForm(request.POST or None, instance=customer)
    if request.method == "POST" and form.is_valid():
        form.save()
    return redirect("erp:customer_list")


def customer_delete(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    if request.method == "POST":
        customer.delete()
    return redirect("erp:customer_list")


def product_list(request):
    products = Product.objects.prefetch_related("aliases", "weight_profiles", "weight_profiles__material", "weight_profiles__color")
    query = request.GET.get("q", "").strip()
    material_id = request.GET.get("material", "")
    include_deleted = request.GET.get("include_deleted") == "1"
    if not include_deleted:
        products = products.filter(is_deleted=False)
    if query:
        products = products.filter(
            Q(code__icontains=query) | Q(name__icontains=query) | Q(aliases__alias__icontains=query)
        ).distinct()
    if material_id.isdigit():
        products = products.filter(Q(material_id=material_id) | Q(weight_profiles__material_id=material_id)).distinct()
    return render(request, "erp/product_list.html", {
        "products": products, "create_form": ProductForm(), "query": query,
        "materials": Material.objects.filter(active=True), "selected_material": material_id,
        "include_deleted": include_deleted,
    })


def product_create(request):
    form = ProductForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("erp:product_list")
    return render(request, "erp/form.html", {"form": form, "title": "상품 등록", "description": "판매 상품과 현재 재고를 등록합니다."})


@require_POST
def product_delete(request, pk):
    product = get_object_or_404(Product, pk=pk, is_deleted=False)
    product.is_deleted = True
    product.deleted_at = timezone.now()
    product.active = False
    product.save(update_fields=["is_deleted", "deleted_at", "active"])
    messages.success(request, f"{product.code} 상품을 삭제 처리했습니다.")
    return redirect("erp:product_list")


@require_POST
def product_restore(request, pk):
    product = get_object_or_404(Product, pk=pk, is_deleted=True)
    product.is_deleted = False
    product.deleted_at = None
    product.active = True
    product.save(update_fields=["is_deleted", "deleted_at", "active"])
    messages.success(request, f"{product.code} 상품을 복구했습니다.")
    return redirect(f"{reverse('erp:product_list')}?include_deleted=1")


@require_POST
def product_catalog_refresh(request):
    result = rebuild_product_weight_profiles()
    messages.success(
        request,
        f"평균중량을 갱신했습니다. 판매 {result['sale_rows']}건 · 매입 {result['purchase_rows']}건 · 평균 {result['profiles']}개",
    )
    return redirect("erp:product_list")


@master_reauthentication_required
def material_list(request):
    form = MaterialForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "재질을 추가했습니다.")
        return redirect("erp:material_list")
    return render(request, "erp/material_list.html", {
        "materials": Material.objects.all(), "form": form,
        "colors": ProductColor.objects.all(), "color_form": ProductColorForm(),
        "company_form": CompanyProfileForm(instance=CompanyProfile.objects.first() or CompanyProfile()),
    })


@require_POST
@master_reauthentication_required
def company_profile_edit(request):
    profile = CompanyProfile.objects.first() or CompanyProfile()
    form = CompanyProfileForm(request.POST, instance=profile)
    if form.is_valid():
        form.save()
        messages.success(request, "명세서 공급자 정보를 수정했습니다.")
    else:
        messages.error(request, "공급자 정보를 확인해 주세요.")
    return redirect("erp:material_list")


@require_POST
@master_reauthentication_required
def material_edit(request, pk):
    material = get_object_or_404(Material, pk=pk)
    form = MaterialForm(request.POST, instance=material)
    if form.is_valid():
        form.save()
        messages.success(request, f"{material.name} 재질을 수정했습니다.")
    else:
        messages.error(request, "재질 정보를 확인해 주세요.")
    return redirect("erp:material_list")


@require_POST
@master_reauthentication_required
def color_create(request):
    form = ProductColorForm(request.POST)
    if form.is_valid():
        form.save()
        messages.success(request, "색상을 추가했습니다.")
    else:
        messages.error(request, "색상 정보를 확인해 주세요.")
    return redirect("erp:material_list")


@require_POST
@master_reauthentication_required
def color_edit(request, pk):
    color = get_object_or_404(ProductColor, pk=pk)
    form = ProductColorForm(request.POST, instance=color)
    if form.is_valid():
        form.save()
        messages.success(request, f"{color.code} 색상을 수정했습니다.")
    else:
        messages.error(request, "색상 정보를 확인해 주세요.")
    return redirect("erp:material_list")
