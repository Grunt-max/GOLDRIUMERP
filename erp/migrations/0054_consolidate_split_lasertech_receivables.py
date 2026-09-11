from django.db import migrations


SPLIT_CUSTOMER_NAMES = (
    "레이저테크_로프",
    "레이저테크_코코",
    "레이저테크_코코2",
)


def consolidate_split_customer_receivables(apps, schema_editor):
    Customer = apps.get_model("erp", "Customer")
    ReceivableAccount = apps.get_model("erp", "ReceivableAccount")
    SaleItem = apps.get_model("erp", "SaleItem")

    customer_ids = list(
        Customer.objects.filter(name__in=SPLIT_CUSTOMER_NAMES).values_list(
            "id", flat=True
        )
    )
    if not customer_ids:
        return

    # These are now independent customers. Any account assignment left from the
    # former shared-customer setup must become part of each customer's default
    # receivable balance so sales, returns and payments offset one another.
    SaleItem.objects.filter(
        transaction__customer_id__in=customer_ids,
    ).exclude(receivable_account=None).update(receivable_account=None)

    ReceivableAccount.objects.filter(customer_id__in=customer_ids).update(active=False)


class Migration(migrations.Migration):
    dependencies = [
        ("erp", "0053_merge_goldjoy_transactions"),
    ]

    operations = [
        migrations.RunPython(
            consolidate_split_customer_receivables,
            migrations.RunPython.noop,
        ),
    ]
