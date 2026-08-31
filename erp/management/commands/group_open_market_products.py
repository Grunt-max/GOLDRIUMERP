from django.core.management.base import BaseCommand

from erp.open_market_matching import group_exact_marketplace_products


class Command(BaseCommand):
    help = "완전히 일치하는 네이버/쿠팡 상품만 오픈마켓 마스터로 통합합니다."

    def handle(self, *args, **options):
        result = group_exact_marketplace_products()
        self.stdout.write(self.style.SUCCESS(
            f"통합 {result['grouped']}쌍, 자동 통합 제외 {result['excluded']}쌍"
        ))
