from django.core.management.base import BaseCommand, CommandError

from erp.marketplaces import MarketplaceError, channel_configuration, fetch_coupang_products, fetch_naver_products
from erp.views import _sync_marketplace_rows


class Command(BaseCommand):
    help = "Read marketplace products and save local snapshots without changing the marketplace."

    def add_arguments(self, parser):
        parser.add_argument("channel", choices=("naver", "coupang"))

    def handle(self, *args, **options):
        channel = options["channel"]
        config = channel_configuration()[channel]
        if not config["configured"]:
            raise CommandError("Missing settings: " + ", ".join(config["missing"]))
        try:
            rows = fetch_naver_products() if channel == "naver" else fetch_coupang_products()
            saved = _sync_marketplace_rows(channel, rows)
        except MarketplaceError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f"{channel}: saved {saved} read-only product snapshots"))
