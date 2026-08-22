from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("erp", "0037_saleitem_returned_from")]

    operations = [
        migrations.AlterField(
            model_name="saleitem",
            name="quantity",
            field=models.DecimalField(decimal_places=2, default=1, max_digits=12, verbose_name="수량"),
        ),
    ]
