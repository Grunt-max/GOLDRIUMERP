import hashlib
import itertools
import json
import re
from decimal import Decimal, InvalidOperation

from django.db import transaction

from .marketplace_rules import naver_option_price_error
from .models import OpenMarketChannelOption, OpenMarketOptionCombination


MAX_COMMON_COMBINATIONS = 1000
MAX_CHANNEL_GROUPS = 3
COUPANG_ITEM_LIMIT = 200


def _safe_identifier(value, fallback):
    cleaned = re.sub(r"[^0-9A-Za-z_-]+", "-", str(value or "")).strip("-")
    return cleaned[:40] or fallback


def _integer(value, field_name):
    try:
        number = Decimal(str(value or 0))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field_name}은 원 단위 숫자로 입력해 주세요.") from exc
    if number != number.to_integral_value():
        raise ValueError(f"{field_name}은 원 단위 정수로 입력해 주세요.")
    return int(number)


def normalize_option_blueprint(value):
    """Validate and normalize the UI JSON without assuming jewellery-specific option names."""
    if value in (None, "", {}):
        return {"groups": []}
    if not isinstance(value, dict) or not isinstance(value.get("groups", []), list):
        raise ValueError("공통 옵션 데이터 형식이 올바르지 않습니다.")
    raw_groups = value.get("groups", [])
    if len(raw_groups) > MAX_CHANNEL_GROUPS:
        raise ValueError("현재 네이버·쿠팡 공통 변환은 옵션 그룹을 최대 3개까지 지원합니다.")
    groups = []
    group_names = set()
    group_ids = set()
    total = 1
    for group_index, raw_group in enumerate(raw_groups, 1):
        name = str(raw_group.get("name", "")).strip()
        if not name:
            raise ValueError(f"{group_index}번째 옵션 그룹명을 입력해 주세요.")
        if name in group_names:
            raise ValueError(f"옵션 그룹명 '{name}'이 중복되었습니다.")
        group_names.add(name)
        group_id = _safe_identifier(raw_group.get("id"), f"group-{group_index}")
        if group_id in group_ids:
            raise ValueError("옵션 그룹 내부 식별자가 중복되었습니다. 해당 그룹을 삭제한 뒤 다시 추가해 주세요.")
        group_ids.add(group_id)
        raw_values = raw_group.get("values", [])
        if not isinstance(raw_values, list) or not raw_values:
            raise ValueError(f"'{name}' 옵션값을 하나 이상 입력해 주세요.")
        values = []
        labels = set()
        value_ids = set()
        for value_index, raw_value in enumerate(raw_values, 1):
            label = str(raw_value.get("label", "")).strip()
            if not label:
                raise ValueError(f"'{name}'의 {value_index}번째 옵션값을 입력해 주세요.")
            if label in labels:
                raise ValueError(f"'{name}'의 옵션값 '{label}'이 중복되었습니다.")
            labels.add(label)
            adjustments = raw_value.get("adjustments") or {}
            value_id = _safe_identifier(raw_value.get("id"), f"value-{value_index}")
            if value_id in value_ids:
                raise ValueError(f"'{name}' 옵션값 내부 식별자가 중복되었습니다. 중복 값을 삭제한 뒤 다시 추가해 주세요.")
            value_ids.add(value_id)
            values.append({
                "id": value_id,
                "label": label,
                "adjustments": {
                    "naver": _integer(adjustments.get("naver", 0), f"{label} 네이버 추가금"),
                    "coupang": _integer(adjustments.get("coupang", 0), f"{label} 쿠팡 추가금"),
                },
            })
        total *= len(values)
        groups.append({"id": group_id, "name": name, "values": values})
    if total > MAX_COMMON_COMBINATIONS:
        raise ValueError(f"공통 옵션 조합은 최대 {MAX_COMMON_COMBINATIONS:,}개까지 만들 수 있습니다. 상품을 나눠 주세요.")
    return {"groups": groups}


def option_combination_count(blueprint):
    groups = (blueprint or {}).get("groups", [])
    if not groups:
        return 0
    count = 1
    for group in groups:
        count *= len(group.get("values", []))
    return count


def _combination_key(rows):
    identity = [{"group": row["group_id"], "value": row["value_id"]} for row in rows]
    return hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _next_option_code(product, sequence):
    base = re.sub(r"[^0-9A-Za-z-]+", "-", product.code).strip("-").upper() or f"ERP-{product.pk}"
    while True:
        candidate = f"{base[:91]}-O{sequence:03d}"
        if not OpenMarketOptionCombination.objects.filter(option_code=candidate).exists():
            return candidate
        sequence += 1


@transaction.atomic
def sync_common_options(product):
    """Generate stable common combinations and project them into each marketplace."""
    blueprint = normalize_option_blueprint(product.option_blueprint)
    groups = blueprint["groups"]
    if not groups:
        raise ValueError("공통 옵션 그룹과 옵션값을 먼저 입력해 주세요.")

    value_sets = []
    for group in groups:
        value_sets.append([{
            "group_id": group["id"], "group": group["name"],
            "value_id": value["id"], "value": value["label"],
            "adjustments": value["adjustments"],
        } for value in group["values"]])

    active_keys = set()
    combinations = []
    created_count = 0
    for sort_order, selected in enumerate(itertools.product(*value_sets)):
        rows = list(selected)
        key = _combination_key(rows)
        active_keys.add(key)
        combination = OpenMarketOptionCombination.objects.filter(product=product, option_key=key).first()
        if combination is None:
            combination = OpenMarketOptionCombination(
                product=product, option_key=key,
                option_code=_next_option_code(product, sort_order + 1),
                stock_quantity=product.option_default_stock,
            )
            created_count += 1
        combination.option_values = rows
        combination.active = True
        combination.sort_order = sort_order
        combination.save()
        combinations.append(combination)

    removed = product.option_combinations.exclude(option_key__in=active_keys)
    removed_ids = list(removed.values_list("id", flat=True))
    removed.update(active=False)
    if removed_ids:
        OpenMarketChannelOption.objects.filter(
            common_combination_id__in=removed_ids,
            external_option_id="", external_item_id="",
        ).update(active=False)

    result = {
        "combinations": len(combinations), "created": created_count,
        "channels": {}, "warnings": [],
    }
    for setting in product.channel_settings.all():
        channel = setting.channel
        if channel not in {"naver", "coupang"}:
            continue
        if setting.option_base_original_price is None or setting.option_base_sale_price is None:
            result["warnings"].append(
                f"{setting.get_channel_display()}: 기준 할인 전 가격과 실제 판매가를 입력하면 마켓 옵션을 만들 수 있습니다."
            )
            continue
        base_original = int(setting.option_base_original_price)
        base_sale = int(setting.option_base_sale_price)
        if base_original < base_sale:
            result["warnings"].append(
                f"{setting.get_channel_display()}: 기준 할인 전 가격은 실제 판매가보다 낮을 수 없어 적용하지 않았습니다."
            )
            continue
        if channel == "coupang" and len(combinations) > COUPANG_ITEM_LIMIT:
            result["warnings"].append(
                f"쿠팡: 옵션 {len(combinations):,}개는 한 상품의 {COUPANG_ITEM_LIMIT:,}개 제한을 넘습니다. 상품을 나눠 주세요."
            )
            continue

        is_uploaded = bool(setting.external_product_id or setting.external_channel_product_id)
        if is_uploaded:
            result["warnings"].append(
                f"{setting.get_channel_display()}: 이미 외부 등록된 상품입니다. "
                "새 공통 옵션은 기존 판매상품과 섞이지 않도록 비활성 초안으로 저장했습니다."
            )
        else:
            setting.selling_options.filter(
                common_combination__isnull=True, generated_from_common=False,
                external_option_id="", external_item_id="",
            ).update(active=False)

        projected_prices = []
        changed = 0
        for combination in combinations:
            adjustment = sum(
                int(row.get("adjustments", {}).get(channel, 0))
                for row in combination.option_values
            )
            original_price = base_original + adjustment
            sale_price = base_sale + adjustment
            if original_price < 0 or sale_price < 0:
                result["warnings"].append(
                    f"{setting.get_channel_display()}: {combination} 조합의 계산 가격이 0원보다 작아 적용하지 않았습니다."
                )
                continue
            projected_prices.append(original_price)
            generated_active = combination.active and not is_uploaded
            option, created = OpenMarketChannelOption.objects.get_or_create(
                setting=setting, common_combination=combination,
                defaults={
                    "option_name_1": combination.option_values[0]["group"],
                    "option_value_1": combination.option_values[0]["value"],
                    "sale_price": sale_price, "original_price": original_price,
                    "stock_quantity": combination.stock_quantity,
                    "sort_order": combination.sort_order,
                    "active": generated_active, "generated_from_common": True,
                    "internal_variant": combination.internal_variant,
                },
            )
            if option.external_option_id or option.external_item_id:
                continue
            rows = combination.option_values + [{}, {}, {}]
            option.option_name_1, option.option_value_1 = rows[0].get("group", "선택"), rows[0].get("value", "")
            option.option_name_2, option.option_value_2 = rows[1].get("group", ""), rows[1].get("value", "")
            option.option_name_3, option.option_value_3 = rows[2].get("group", ""), rows[2].get("value", "")
            option.generated_from_common = True
            option.sort_order = combination.sort_order
            option.active = generated_active
            option.internal_variant = combination.internal_variant
            if not option.manual_override:
                option.original_price = original_price
                option.sale_price = sale_price
                option.stock_quantity = combination.stock_quantity
            option.save()
            changed += 1

        stale = setting.selling_options.filter(generated_from_common=True).exclude(
            common_combination__option_key__in=active_keys,
        ).filter(external_option_id="", external_item_id="")
        stale.update(active=False)
        result["channels"][channel] = changed
        if channel == "naver":
            price_error = naver_option_price_error(projected_prices)
            if price_error:
                result["warnings"].append(f"네이버 가격 확인: {price_error}")
    return result
