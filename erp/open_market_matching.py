import re
from decimal import Decimal
from difflib import SequenceMatcher

from django.db import transaction
from django.utils import timezone

from .models import MarketplaceProduct, OpenMarketChannelSetting, OpenMarketMatchCandidate, OpenMarketProduct, OpenMarketVariant


def normalized_market_name(value):
    value = re.sub(r"^\[[^\]]+\]\s*", "", (value or "").lower())
    return re.sub(r"[^0-9a-z가-힣]", "", value)


def _ensure_default_variants(master):
    for channel in ("naver", "coupang"):
        OpenMarketChannelSetting.objects.get_or_create(
            product=master, channel=channel,
            defaults={"delivery_method": "DELIVERY" if channel == "naver" else "SEQUENCIAL"},
        )
    for code in ("14KY", "14KP", "18KY", "18KP"):
        OpenMarketVariant.objects.get_or_create(
            product=master, base_variant=code, specifications={},
            defaults={"sku": f"{master.code}-{code}"},
        )


@transaction.atomic
def group_exact_marketplace_products():
    """Group only identical normalized titles; fuzzy matches remain review-only."""
    naver_rows = list(MarketplaceProduct.objects.filter(channel="naver"))
    coupang_rows = list(MarketplaceProduct.objects.filter(channel="coupang"))
    naver_by_name = {normalized_market_name(row.name): row for row in naver_rows}
    grouped = 0
    pending = 0
    for coupang in coupang_rows:
        normalized = normalized_market_name(coupang.name)
        exact_naver = naver_by_name.get(normalized)
        if exact_naver:
            candidate, _ = OpenMarketMatchCandidate.objects.update_or_create(
                naver_listing=exact_naver, coupang_listing=coupang,
                defaults={"name_score": Decimal("1"), "status": "confirmed",
                          "reason": "채널명 접두어와 기호를 제거한 상품명이 완전히 동일",
                          "reviewed_at": timezone.now()},
            )
            master = exact_naver.master_product or coupang.master_product
            if master is None:
                base_code = f"OM-N-{exact_naver.external_product_id}"[:40]
                code = base_code
                suffix = 1
                while OpenMarketProduct.objects.filter(code=code).exists():
                    suffix += 1
                    code = f"{base_code[:35]}-{suffix}"
                master = OpenMarketProduct.objects.create(code=code, name=exact_naver.name, active=False)
            _ensure_default_variants(master)
            MarketplaceProduct.objects.filter(pk__in=(exact_naver.pk, coupang.pk)).update(master_product=master)
            grouped += 1
            continue

        if not naver_rows:
            continue
        score, closest = max(
            ((SequenceMatcher(None, normalized, normalized_market_name(row.name)).ratio(), row)
             for row in naver_rows), key=lambda pair: pair[0],
        )
        OpenMarketMatchCandidate.objects.update_or_create(
            naver_listing=closest, coupang_listing=coupang,
            defaults={"name_score": Decimal(str(round(score, 4))), "status": "excluded",
                      "reason": "상품명이 완전히 같지 않아 자동 통합에서 제외", "reviewed_at": None},
        )
        pending += 1
    return {"grouped": grouped, "excluded": pending}
