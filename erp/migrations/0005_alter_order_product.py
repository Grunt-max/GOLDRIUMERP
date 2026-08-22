import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("erp", "0004_material_product_material_product_default_weight_and_more")]

    operations = [
        migrations.AlterField(
            model_name="order",
            name="product",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to="erp.product", verbose_name="카탈로그 상품"),
        ),
    ]
