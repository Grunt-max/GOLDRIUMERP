from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("erp", "0008_copy_legacy_orders_to_sales")]
    operations = [
        migrations.AddField(
            model_name="customer",
            name="default_loss_rate",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=6, null=True, verbose_name="기본 해리율(%)"),
        ),
        migrations.AddField(
            model_name="product",
            name="default_loss_rate",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=6, null=True, verbose_name="제품 해리율(%)"),
        ),
    ]
