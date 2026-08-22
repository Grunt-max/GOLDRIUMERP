from django.db import migrations
from django.db.models import Sum


def copy_legacy_orders(apps, schema_editor):
    Order = apps.get_model("erp", "Order")
    SaleTransaction = apps.get_model("erp", "SaleTransaction")
    SaleItem = apps.get_model("erp", "SaleItem")
    for order in Order.objects.select_related("material").all().iterator():
        transaction_no = order.transaction_no or f"LEGACY-{order.pk}"
        sale, _ = SaleTransaction.objects.get_or_create(
            transaction_no=transaction_no,
            defaults={
                "customer_id": order.customer_id,
                "sale_date": order.ordered_at,
                "status": order.status,
                "memo": order.memo,
            },
        )
        SaleItem.objects.get_or_create(
            legacy_order_id=order.pk,
            defaults={
                "transaction_id": sale.pk,
                "product_id": order.product_id,
                "model_number": order.model_number,
                "material_id": order.material_id,
                "weight": order.weight,
                "quantity": order.quantity,
                "loss_rate": order.loss_rate,
                "pure_gold_weight": order.pure_gold_weight,
                "unit_price": order.unit_price,
                "labor_amount": order.labor_amount,
                "memo": order.memo[:200],
            },
        )
    for sale in SaleTransaction.objects.all().iterator():
        totals = sale.items.aggregate(
            pure=Sum("pure_gold_weight"), labor=Sum("labor_amount")
        )
        cash = sum((item.unit_price * item.quantity for item in sale.items.all()), 0)
        linked_orders = Order.objects.filter(migrated_sale_item__transaction=sale)
        paid_cash = sum((order.paid_amount for order in linked_orders), 0)
        paid_labor = sum((order.paid_labor_amount for order in linked_orders), 0)
        sale.total_pure_gold_weight = totals["pure"] or 0
        sale.total_cash_amount = cash
        sale.total_labor_amount = totals["labor"] or 0
        sale.paid_cash_amount = paid_cash
        sale.paid_labor_amount = paid_labor
        sale.gold_receivable = sale.total_pure_gold_weight
        sale.cash_receivable = max(sale.total_cash_amount - paid_cash, 0)
        sale.labor_receivable = max(sale.total_labor_amount - paid_labor, 0)
        sale.save()


class Migration(migrations.Migration):
    dependencies = [("erp", "0007_saletransaction_saleitem")]
    operations = [migrations.RunPython(copy_legacy_orders, migrations.RunPython.noop)]
