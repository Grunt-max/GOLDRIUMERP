from django.core.management.base import BaseCommand, CommandError

from erp.gold_prices import collect_gold_prices


class Command(BaseCommand):
    help = "삼성금거래소 소매·도매 102% 시세를 수집합니다."

    def handle(self, *args, **options):
        try:
            retail, wholesale = collect_gold_prices()
        except Exception as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(
            f"소매 {retail.price_date} {retail.applied_price_per_gram:,.0f}원/g, "
            f"도매 {wholesale.price_date} {wholesale.applied_price_per_gram:,.0f}원/g"
        ))
