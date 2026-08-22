from django.db import migrations, models
import erp.models


def renumber_existing_sales(apps, schema_editor):
    SaleTransaction = apps.get_model("erp", "SaleTransaction")
    DailySaleSequence = apps.get_model("erp", "DailySaleSequence")
    dates = SaleTransaction.objects.order_by().values_list("sale_date", flat=True).distinct()
    for sale_date in dates:
        sales = SaleTransaction.objects.filter(sale_date=sale_date).order_by("id")
        count = 0
        for count, sale in enumerate(sales, start=1):
            sale.transaction_no = f"{sale_date:%y%m%d}{count:05d}"
            sale.save(update_fields=["transaction_no"])
        DailySaleSequence.objects.update_or_create(sale_date=sale_date, defaults={"last_sequence": count})


class Migration(migrations.Migration):
    dependencies = [("erp", "0010_unit_price_is_labor")]
    operations = [
        migrations.CreateModel(
            name="DailySaleSequence",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("sale_date", models.DateField(unique=True, verbose_name="거래일")),
                ("last_sequence", models.PositiveIntegerField(default=0, verbose_name="마지막 순번")),
            ],
            options={"ordering": ["-sale_date"]},
        ),
        migrations.RunPython(renumber_existing_sales, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="saletransaction",
            name="transaction_no",
            field=models.CharField(default=erp.models.generate_transaction_no, max_length=11, unique=True, verbose_name="거래번호"),
        ),
    ]
