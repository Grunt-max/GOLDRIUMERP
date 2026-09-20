from django.db import migrations, models


ACCOUNT_CUSTOMER_NAMES = {"jdl", "골드팡", "주엔", "덕신사", "구디컴퍼니"}


def classify_customers(apps, schema_editor):
    Customer = apps.get_model("erp", "Customer")
    Customer.objects.update(settlement_type="cash")
    account_ids = [
        customer.pk
        for customer in Customer.objects.all()
        if customer.name.strip().casefold() in ACCOUNT_CUSTOMER_NAMES
    ]
    Customer.objects.filter(pk__in=account_ids).update(settlement_type="account")


class Migration(migrations.Migration):
    dependencies = [("erp", "0058_customer_settlement_type")]

    operations = [
        migrations.AlterField(
            model_name="customer",
            name="settlement_type",
            field=models.CharField(
                choices=[("account", "계좌 거래처"), ("cash", "현금 거래처")],
                default="cash",
                max_length=10,
                verbose_name="정산 구분",
            ),
        ),
        migrations.RunPython(classify_customers, migrations.RunPython.noop),
    ]
