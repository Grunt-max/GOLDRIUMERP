from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("erp", "0005_alter_order_product")]

    operations = [
        migrations.AddField(
            model_name="order", name="labor_amount",
            field=models.DecimalField(decimal_places=0, default=0, max_digits=12, verbose_name="공임"),
        ),
        migrations.AddField(
            model_name="order", name="paid_labor_amount",
            field=models.DecimalField(decimal_places=0, default=0, max_digits=12, verbose_name="공임 입금액"),
        ),
    ]
