import re
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction

from .models import Order, Product, ProductAlias, ProductWeightProfile, PurchaseEntry, SaleItem


WEIGHT_QUANTUM = Decimal("0.001")


def canonical_product_code(code):
    """Treat a trailing B/N marker as a bracelet/necklace variant of one item."""
    value = (code or "").strip()
    return re.sub(r"(?i)(?:[/_-]?[BN])$", "", value).strip() or value


@transaction.atomic
def merge_bn_product_variants():
    groups = defaultdict(list)
    for product in Product.objects.all().order_by("id"):
        groups[canonical_product_code(product.code).casefold()].append(product)

    merged = renamed = 0
    for products in groups.values():
        base_code = canonical_product_code(products[0].code)
        canonical = next((p for p in products if p.code.casefold() == base_code.casefold()), products[0])
        original_codes = [p.code for p in products]
        if canonical.code != base_code and not Product.objects.filter(code__iexact=base_code).exclude(pk=canonical.pk).exists():
            old_code = canonical.code
            canonical.code = base_code
            if canonical.name == old_code:
                canonical.name = base_code
            canonical.save(update_fields=["code", "name"])
            renamed += 1

        for duplicate in products:
            if duplicate.pk == canonical.pk:
                continue
            SaleItem.objects.filter(product=duplicate).update(product=canonical)
            Order.objects.filter(product=duplicate).update(product=canonical)
            for alias in duplicate.aliases.all():
                ProductAlias.objects.get_or_create(alias=alias.alias, defaults={"product": canonical})
            if not canonical.image and duplicate.image:
                canonical.image = duplicate.image
                canonical.save(update_fields=["image"])
            duplicate.delete()
            merged += 1

        for alias in original_codes:
            if alias.casefold() != canonical.code.casefold():
                ProductAlias.objects.update_or_create(alias=alias, defaults={"product": canonical})
    return {"merged": merged, "renamed": renamed}


def _average(total_weight, total_units):
    if not total_units:
        return None
    return (total_weight / total_units).quantize(WEIGHT_QUANTUM, rounding=ROUND_HALF_UP)


@transaction.atomic
def rebuild_product_weight_profiles():
    sale_groups = defaultdict(lambda: {"weight": Decimal("0"), "units": Decimal("0"), "rows": 0})
    sale_items = SaleItem.objects.filter(
        entry_type="sale", is_deleted=False, transaction__status__in=("new", "done"),
        product__isnull=False, material__isnull=False, weight__gt=0, quantity__gt=0,
    ).select_related("product", "material", "color")
    for item in sale_items:
        key = (item.product_id, item.material_id, item.color_id)
        sale_groups[key]["weight"] += item.weight
        sale_groups[key]["units"] += item.quantity
        sale_groups[key]["rows"] += 1

    products = list(Product.objects.prefetch_related("aliases"))
    product_lookup = {}
    for product in products:
        product_lookup[product.code.casefold()] = product
        product_lookup[canonical_product_code(product.code).casefold()] = product
        for alias in product.aliases.all():
            product_lookup[alias.alias.casefold()] = product
            product_lookup[canonical_product_code(alias.alias).casefold()] = product

    purchase_groups = defaultdict(lambda: {"weight": Decimal("0"), "units": Decimal("0"), "rows": 0})
    legacy_purchase_items = SaleItem.objects.filter(
        entry_type="sale", is_deleted=False, transaction__status__in=("new", "done"),
        product__isnull=False, material__isnull=False, purchase_supplier__isnull=False,
        weight__gt=0, quantity__gt=0,
    )
    for item in legacy_purchase_items:
        key = (item.product_id, item.material_id, item.color_id)
        purchase_groups[key]["weight"] += item.weight
        purchase_groups[key]["units"] += item.quantity
        purchase_groups[key]["rows"] += 1
    purchase_items = PurchaseEntry.objects.filter(
        is_deleted=False, actual_weight__gt=0,
    ).select_related("material")
    for item in purchase_items:
        product = product_lookup.get(item.item_name.strip().casefold()) or product_lookup.get(
            canonical_product_code(item.item_name).casefold()
        )
        if not product:
            continue
        key = (product.pk, item.material_id, None)
        purchase_groups[key]["weight"] += item.actual_weight
        purchase_groups[key]["units"] += Decimal("1")
        purchase_groups[key]["rows"] += 1

    ProductWeightProfile.objects.all().delete()
    keys = set(sale_groups) | set(purchase_groups)
    profiles = []
    for product_id, material_id, color_id in keys:
        sale = sale_groups.get((product_id, material_id, color_id))
        purchase = purchase_groups.get((product_id, material_id, color_id))
        if purchase is None and color_id is not None:
            purchase = purchase_groups.get((product_id, material_id, None))
        sale_average = _average(sale["weight"], sale["units"]) if sale else None
        purchase_average = _average(purchase["weight"], purchase["units"]) if purchase else None
        recommended = sale_average if sale_average is not None else purchase_average
        if recommended is None:
            continue
        profiles.append(ProductWeightProfile(
            product_id=product_id, material_id=material_id, color_id=color_id,
            sale_average_weight=sale_average, sale_sample_count=sale["rows"] if sale else 0,
            purchase_average_weight=purchase_average, purchase_sample_count=purchase["rows"] if purchase else 0,
            average_weight=recommended,
        ))
    ProductWeightProfile.objects.bulk_create(profiles)

    for product in Product.objects.prefetch_related("weight_profiles"):
        candidates = list(product.weight_profiles.all())
        if not candidates:
            continue
        matching = [p for p in candidates if p.material_id == product.material_id and p.color_id == product.color_id]
        selected = max(matching or candidates, key=lambda p: (p.sale_sample_count, p.purchase_sample_count))
        if product.default_weight != selected.average_weight:
            product.default_weight = selected.average_weight
            product.save(update_fields=["default_weight"])
    return {
        "profiles": len(profiles), "sale_rows": sale_items.count(),
        "purchase_rows": purchase_items.count() + legacy_purchase_items.count(),
    }
