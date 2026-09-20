from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.utils.dateparse import parse_date

from erp.marketplaces import MarketplaceError, channel_configuration, fetch_coupang_settlements, fetch_naver_settlements
from erp.views import _sync_marketplace_settlements


class Command(BaseCommand):
    help = "Collect marketplace orders for a date range and update local sales snapshots."

    def add_arguments(self, parser):
        parser.add_argument("channel", choices=("naver", "coupang"))
        parser.add_argument("--start")
        parser.add_argument("--end")

    def handle(self, *args, **options):
        channel = options["channel"]
        today = timezone.localdate()
        start_date = parse_date(options["start"] or "") or today - timedelta(days=179)
        end_date = parse_date(options["end"] or "") or today
        if start_date > end_date:
            raise CommandError("Start date must not be later than end date.")
        config = channel_configuration()[channel]
        if not config["configured"]:
            raise CommandError("Missing settings: " + ", ".join(config["missing"]))
        try:
            rows = fetch_naver_settlements(start_date, end_date) if channel == "naver" else fetch_coupang_settlements(start_date, end_date)
            saved = _sync_marketplace_settlements(channel, rows)
        except MarketplaceError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(
            f"{channel}: saved {saved} settlement rows for {start_date} through {end_date}"
        ))
