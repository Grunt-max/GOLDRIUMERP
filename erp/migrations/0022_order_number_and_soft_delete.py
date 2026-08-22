from django.db import migrations, models


def assign_order_numbers(apps, schema_editor):
    Order = apps.get_model("erp", "Order")
    DailyOrderSequence = apps.get_model("erp", "DailyOrderSequence")
    current_date = None
    sequence = 0
    for order in Order.objects.order_by("ordered_at", "id"):
        if order.ordered_at != current_date:
            current_date = order.ordered_at
            sequence = 0
        sequence += 1
        order.transaction_no = f"{current_date:%y%m%d}{sequence:03d}"
        order.save(update_fields=["transaction_no"])
        DailyOrderSequence.objects.update_or_create(
            order_date=current_date, defaults={"last_sequence": sequence}
        )


class Migration(migrations.Migration):
    dependencies = [("erp", "0021_order_completed_at")]
    operations = [
        migrations.CreateModel(
            name="DailyOrderSequence",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("order_date", models.DateField(unique=True, verbose_name="주문일")),
                ("last_sequence", models.PositiveIntegerField(default=0, verbose_name="마지막 순번")),
            ],
            options={"ordering": ["-order_date"]},
        ),
        migrations.AddField(
            model_name="order", name="is_deleted",
            field=models.BooleanField(db_index=True, default=False, verbose_name="삭제 여부"),
        ),
        migrations.AddField(
            model_name="order", name="deleted_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="삭제일시"),
        ),
        migrations.RunPython(assign_order_numbers, migrations.RunPython.noop),
    ]
