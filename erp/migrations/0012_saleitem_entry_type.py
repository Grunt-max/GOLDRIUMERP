from django.db import migrations, models


def preserve_header_payments(apps, schema_editor):
    SaleTransaction = apps.get_model("erp", "SaleTransaction")
    SaleItem = apps.get_model("erp", "SaleItem")
    Material = apps.get_model("erp", "Material")
    payment_material = Material.objects.filter(name="24K").first() or Material.objects.first()
    for sale in SaleTransaction.objects.all().iterator():
        if sale.paid_gold_weight or sale.paid_labor_amount:
            SaleItem.objects.create(
                transaction_id=sale.pk,
                entry_type="payment",
                model_number="기존결제",
                material_id=payment_material.pk if payment_material else None,
                weight=sale.paid_gold_weight,
                quantity=1,
                loss_rate=0,
                pure_gold_weight=sale.paid_gold_weight,
                unit_price=sale.paid_labor_amount,
                labor_amount=0,
                memo="기존 거래 결제 이관",
            )


class Migration(migrations.Migration):
    dependencies = [("erp", "0011_daily_sale_sequence")]
    operations = [
        migrations.AddField(
            model_name="saleitem",
            name="entry_type",
            field=models.CharField(choices=[("sale", "판매"), ("payment", "결제")], db_index=True, default="sale", max_length=10, verbose_name="구분"),
        ),
        migrations.RunPython(preserve_header_payments, migrations.RunPython.noop),
    ]
