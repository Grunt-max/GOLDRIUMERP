from django.http import HttpResponseForbidden

from config.views import MASTER_USERNAME
from .access import allowed_sections_for


ROUTE_SECTIONS = {
    "dashboard": "dashboard",
    "gold_price_list": "gold_prices", "gold_price_refresh": "gold_prices", "gold_price_save": "gold_prices",
    "order_list": "orders", "order_customer_outstanding": "orders", "order_create": "orders",
    "order_bulk_action": "orders", "order_edit": "orders", "order_complete": "orders",
    "daily_activity_list": "activities", "daily_activity_create": "activities", "daily_activity_delete": "activities",
    "gold_ledger_list": "gold_ledger", "gold_ledger_create": "gold_ledger", "gold_ledger_delete": "gold_ledger",
    "purchase_list": "purchases", "purchase_create": "purchases", "purchase_supplier_create": "purchases", "purchase_delete": "purchases",
    "sales_list": "sales", "monthly_customer_sales": "sales", "sale_create": "sales",
    "sale_transaction_detail": "sales", "receivables_list": "sales", "customer_ledger": "sales",
    "customer_sales_summary": "sales", "customer_sales_history": "sales", "sales_merge": "sales",
    "sales_split": "sales", "sales_return": "sales", "sales_soft_delete": "sales",
    "customer_list": "customers", "customer_lookup": "customers", "customer_create": "customers",
    "customer_edit": "customers", "customer_delete": "customers",
    "product_list": "products", "product_search": "products", "product_create": "products",
    "product_catalog_refresh": "products", "product_delete": "products", "product_restore": "products",
    "marketplace_list": "marketplaces", "marketplace_master_products": "marketplaces",
    "marketplace_master_product_detail": "marketplaces", "marketplace_channel_items": "marketplaces",
    "marketplace_sales_overview": "marketplaces", "marketplace_product_detail": "marketplaces",
    "marketplace_product_import": "marketplaces", "marketplace_sync": "marketplaces",
}


class EmployeeReadOnlyMiddleware:
    """Limit employee accounts to granted GET screens; every mutation stays master-only."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        user = request.user
        if not user.is_authenticated or user.username == MASTER_USERNAME:
            return None
        match = request.resolver_match
        url_name = match.url_name if match else ""
        if url_name == "logout":
            return None
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            return HttpResponseForbidden("조회 전용 계정은 자료를 등록·변경·삭제할 수 없습니다.")
        if match and match.namespace == "admin":
            return HttpResponseForbidden("관리자 화면은 master 계정만 이용할 수 있습니다.")
        if url_name in ("basic_management_login", "initial_admin_setup", "access_management"):
            return HttpResponseForbidden("권한관리와 기초관리는 master 계정만 이용할 수 있습니다.")
        section = ROUTE_SECTIONS.get(url_name)
        if section and section not in allowed_sections_for(user):
            return HttpResponseForbidden("이 메뉴의 조회 권한이 없습니다.")
        return None
