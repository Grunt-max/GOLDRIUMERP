from decimal import Decimal

from django.db import migrations


TARGET_TRANSACTION_NO = "26090300001"
SOURCE_TRANSACTION_NO = "26090300003"
CUSTOMER_NAME = "골드조이"


def merge_goldjoy_transactions(apps, schema_editor):
    SaleTransaction = apps.get_model("erp", "SaleTransaction")
    SaleItem = apps.get_model("erp", "SaleItem")

    target = SaleTransaction.objects.filter(
        transaction_no=TARGET_TRANSACTION_NO,
        customer__name=CUSTOMER_NAME,
    ).first()
    source = SaleTransaction.objects.filter(
        transaction_no=SOURCE_TRANSACTION_NO,
        customer__name=CUSTOMER_NAME,
    ).first()
    if not target or not source or target.customer_id != source.customer_id:
        return

    SaleItem.objects.filter(transaction=source).update(transaction=target)
    source.delete()

    items = list(SaleItem.objects.filter(transaction=target, is_deleted=False))
    sales = [item for item in items if item.entry_type == "sale"]
    returns = [item for item in items if item.entry_type == "return"]
    payments = [item for item in items if item.entry_type == "payment"]
    adjustments = [item for item in items if item.entry_type in ("wg", "dc", "vd")]

    total_gold = sum((item.pure_gold_weight for item in sales), Decimal("0"))
    total_labor = sum(
        (
            item.labor_total_override
            if item.labor_total_override is not None
            else item.unit_price * item.quantity
            for item in sales
        ),
        Decimal("0"),
    )
    returned_gold = sum((item.pure_gold_weight for item in returns), Decimal("0"))
    returned_labor = sum(
        (
            item.labor_total_override
            if item.labor_total_override is not None
            else item.unit_price * item.quantity
            for item in returns
        ),
        Decimal("0"),
    )
    paid_gold = sum((item.pure_gold_weight for item in payments), Decimal("0"))
    paid_labor = sum(
        (
            item.labor_total_override
            if item.labor_total_override is not None
            else item.unit_price * item.quantity
            for item in payments
        ),
        Decimal("0"),
    )
    adjusted_gold = sum((item.pure_gold_weight for item in adjustments), Decimal("0"))
    adjusted_labor = sum(
        (
            item.labor_total_override
            if item.labor_total_override is not None
            else item.unit_price * item.quantity
            for item in adjustments
            if item.entry_type in ("dc", "vd")
        ),
        Decimal("0"),
    )

    SaleTransaction.objects.filter(pk=target.pk).update(
        total_pure_gold_weight=total_gold,
        total_cash_amount=Decimal("0"),
        total_labor_amount=total_labor,
        paid_gold_weight=paid_gold,
        paid_cash_amount=Decimal("0"),
        paid_labor_amount=paid_labor,
        gold_receivable=total_gold - returned_gold - paid_gold - adjusted_gold,
        cash_receivable=Decimal("0"),
        labor_receivable=total_labor - returned_labor - paid_labor - adjusted_labor,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("erp", "0052_enable_split_lasertech_customers_for_sales"),
    ]

    operations = [
        migrations.RunPython(merge_goldjoy_transactions, migrations.RunPython.noop),
    ]
