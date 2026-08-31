import re
from datetime import date
from decimal import Decimal
from urllib.request import Request, urlopen

from django.utils import timezone

from .models import GoldPrice


RETAIL_URL = "https://samsunggold.co.kr/some/"
WHOLESALE_URL = "https://samsunggold.co.kr/"
DATE_PATTERN = re.compile(r"(20\d{2})년\s*</font>.*?(\d{2})\.(\d{2})", re.S)
RETAIL_PRICE_PATTERN = re.compile(r'<span[^>]*font-size:45px;[^>]*>([\d,]+)</span>')
WHOLESALE_GRAM_PATTERN = re.compile(r'id="t_gold1020"[^>]*>\s*([\d,]+)\s*</div>', re.S)
WHOLESALE_DON_PATTERN = re.compile(r'id="t_gold3751020"[^>]*>\s*([\d,]+)\s*</div>', re.S)
HOME_DATE_PATTERN = re.compile(r"(20\d{2})년\s*(\d{2})월\s*(\d{2})일")


def _download(url):
    request = Request(url, headers={"User-Agent": "GoldriumERP/1.0 (+price-check)"})
    with urlopen(request, timeout=20) as response:
        return response.read().decode("utf-8", errors="replace")


def _number(value):
    return Decimal(value.replace(",", ""))


def collect_gold_prices():
    retail_html = _download(RETAIL_URL)
    wholesale_html = _download(WHOLESALE_URL)

    retail_date_match = DATE_PATTERN.search(retail_html)
    retail_prices = RETAIL_PRICE_PATTERN.findall(retail_html)
    wholesale_date_match = HOME_DATE_PATTERN.search(wholesale_html)
    wholesale_gram_match = WHOLESALE_GRAM_PATTERN.search(wholesale_html)
    wholesale_don_match = WHOLESALE_DON_PATTERN.search(wholesale_html)
    if not retail_date_match or not retail_prices:
        raise ValueError("소매 시세 페이지 구조를 확인할 수 없습니다.")
    if not wholesale_date_match or not wholesale_gram_match or not wholesale_don_match:
        raise ValueError("도매 102% 시세 페이지 구조를 확인할 수 없습니다.")

    retail_date = date(*map(int, retail_date_match.groups()))
    wholesale_date = date(*map(int, wholesale_date_match.groups()))
    collected_at = timezone.now()
    retail, _ = GoldPrice.objects.update_or_create(
        market_type="retail", price_date=retail_date,
        defaults={
            "source_price_per_gram": _number(retail_prices[0]),
            "source_price_per_don": None,
            "application_rate": Decimal("102.00"),
            "source_name": "삼성금거래소 소매 시세",
            "source_url": RETAIL_URL,
            "collected_at": collected_at,
            "is_confirmed": True,
            "memo": "자동 수집: 순금 100% 기준가 × 102% ÷ 1.1 (부가세 별도)",
        },
    )
    wholesale, _ = GoldPrice.objects.update_or_create(
        market_type="wholesale", price_date=wholesale_date,
        defaults={
            "source_price_per_gram": _number(wholesale_gram_match.group(1)),
            "source_price_per_don": _number(wholesale_don_match.group(1)),
            "application_rate": Decimal("102.00"),
            "source_name": "삼성금거래소 도매 102% 기준가",
            "source_url": WHOLESALE_URL,
            "collected_at": collected_at,
            "is_confirmed": True,
            "memo": "자동 수집: 국내 금 102% 기준가",
        },
    )
    return retail, wholesale
