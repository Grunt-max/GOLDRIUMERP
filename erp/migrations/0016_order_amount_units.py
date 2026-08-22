from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("erp", "0015_order_quick_photo_workflow")]

    operations = [
        migrations.AlterField(
            model_name="order", name="quantity",
            field=models.DecimalField(decimal_places=2, default=1, max_digits=10, verbose_name="주문량"),
        ),
        migrations.AlterField(
            model_name="order", name="fulfilled_quantity",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10, verbose_name="출고량"),
        ),
    ]
