import json

from django.core.management.base import BaseCommand

from erp.product_catalog import merge_bn_product_variants, rebuild_product_weight_profiles


class Command(BaseCommand):
    help = "B/N 상품을 통합하고 판매·매입 이력의 재질/색상별 평균중량을 다시 계산합니다."

    def add_arguments(self, parser):
        parser.add_argument("--merge-bn", action="store_true")

    def handle(self, *args, **options):
        result = {}
        if options["merge_bn"]:
            result["variants"] = merge_bn_product_variants()
        result["weights"] = rebuild_product_weight_profiles()
        self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))
