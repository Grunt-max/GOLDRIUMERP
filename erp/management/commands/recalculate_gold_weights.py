from django.core.management.base import BaseCommand
from django.db import transaction

from erp.models import GoldLedgerEntry, Order, PurchaseEntry, SaleItem, SaleTransaction


class Command(BaseCommand):
    help = "Recalculate gold weights: loss for 14K/18K, base gold for 24K, zero gold for silver."

    @transaction.atomic
    def handle(self, *args, **options):
        sale_count = 0
        for item in SaleItem.objects.select_related("material", "product").iterator():
            expected = item.calculate_pure_gold_weight()
            if item.pure_gold_weight != expected:
                SaleItem.objects.filter(pk=item.pk).update(pure_gold_weight=expected)
                sale_count += 1

        order_count = 0
        for order in Order.objects.select_related("material").iterator():
            expected = order.calculate_pure_gold_weight()
            if order.pure_gold_weight != expected:
                Order.objects.filter(pk=order.pk).update(pure_gold_weight=expected)
                order_count += 1

        purchase_count = 0
        for item in PurchaseEntry.objects.select_related("material").iterator():
            # Use the model save path to preserve its defined 0.001 rounding.
            original = item.pure_gold_weight
            item.save(update_fields=["pure_gold_weight"])
            if item.pure_gold_weight != original:
                purchase_count += 1

        ledger_count = 0
        for entry in GoldLedgerEntry.objects.select_related("material").iterator():
            original = entry.pure_gold_weight
            entry.save(update_fields=["material", "actual_weight", "pure_gold_weight"])
            if entry.pure_gold_weight != original:
                ledger_count += 1

        for sale in SaleTransaction.objects.iterator():
            sale.refresh_totals()

        self.stdout.write(self.style.SUCCESS(
            f"Recalculated sales={sale_count}, orders={order_count}, purchases={purchase_count}, ledger={ledger_count}, transactions={SaleTransaction.objects.count()}"
        ))
