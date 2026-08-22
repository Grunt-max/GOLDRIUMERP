from django.db import migrations


def recalculate_sales(apps, schema_editor):
    SaleTransaction = apps.get_model("erp", "SaleTransaction")
    for sale in SaleTransaction.objects.all().iterator():
        labor_total = sum((item.unit_price * item.quantity for item in sale.items.all()), 0)
        sale.paid_labor_amount = min(sale.paid_labor_amount + sale.paid_cash_amount, labor_total)
        sale.paid_cash_amount = 0
        sale.total_cash_amount = 0
        sale.cash_receivable = 0
        sale.total_labor_amount = labor_total
        sale.labor_receivable = max(labor_total - sale.paid_labor_amount, 0)
        sale.save(update_fields=["paid_labor_amount", "paid_cash_amount", "total_cash_amount", "cash_receivable", "total_labor_amount", "labor_receivable"])


class Migration(migrations.Migration):
    dependencies = [("erp", "0009_customer_and_product_loss_rates")]
    operations = [migrations.RunPython(recalculate_sales, migrations.RunPython.noop)]
