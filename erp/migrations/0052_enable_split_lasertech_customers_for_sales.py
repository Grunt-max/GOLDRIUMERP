from django.db import migrations


SPLIT_CUSTOMER_NAMES = (
    "레이저테크_로프",
    "레이저테크_코코",
    "레이저테크_코코2",
)


def enable_split_customers_for_sales(apps, schema_editor):
    Customer = apps.get_model("erp", "Customer")
    Customer.objects.filter(name__in=SPLIT_CUSTOMER_NAMES).update(
        customer_type="sales",
        receivable_accounts_enabled=False,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("erp", "0051_receivableaccount_opening_date_and_more"),
    ]

    operations = [
        migrations.RunPython(enable_split_customers_for_sales, migrations.RunPython.noop),
    ]
