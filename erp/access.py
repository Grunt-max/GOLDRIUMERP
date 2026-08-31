from functools import wraps
from urllib.parse import urlencode

from django.http import HttpResponseForbidden
from django.shortcuts import redirect
from django.urls import reverse

from config.views import MASTER_USERNAME


ERP_SECTIONS = (
    ("dashboard", "대시보드"),
    ("gold_prices", "금시세"),
    ("orders", "주문관리"),
    ("activities", "당일행적"),
    ("gold_ledger", "금 수불관리"),
    ("purchases", "매입관리"),
    ("sales", "판매관리·월별 매출·미수현황"),
    ("customers", "거래처관리"),
    ("products", "상품·카탈로그"),
    ("marketplaces", "오픈마켓관리"),
)


def allowed_sections_for(user):
    if not user.is_authenticated:
        return set()
    if user.username == MASTER_USERNAME:
        return {key for key, _label in ERP_SECTIONS}
    try:
        return set(user.erp_access_profile.allowed_sections)
    except AttributeError:
        return set()


def master_reauthentication_required(view_func):
    """Protect basic-management pages and mutations with step-up authentication."""
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if request.user.username != MASTER_USERNAME:
            return HttpResponseForbidden("기초관리는 master 계정만 이용할 수 있습니다.")
        if request.session.get("basic_management_verified_user_id") != request.user.pk:
            query = urlencode({"next": request.get_full_path()})
            return redirect(f"{reverse('basic_management_login')}?{query}")
        return view_func(request, *args, **kwargs)
    return wrapped
