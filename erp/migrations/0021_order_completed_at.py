from django.db import migrations, models


def populate_completed_dates(apps, schema_editor):
    Order = apps.get_model("erp", "Order")
    for order in Order.objects.filter(status="done", completed_at__isnull=True).iterator():
        order.completed_at = order.ordered_at
        order.save(update_fields=["completed_at"])


class Migration(migrations.Migration):
    dependencies = [("erp", "0020_customer_supplier_name_override")]
    operations = [
        migrations.AddField(
            model_name="order", name="completed_at",
            field=models.DateField(blank=True, db_index=True, null=True, verbose_name="완료일"),
        ),
        migrations.RunPython(populate_completed_dates, migrations.RunPython.noop),
    ]
