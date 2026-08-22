from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("erp", "0012_saleitem_entry_type")]
    operations = [
        migrations.AlterField(
            model_name="saleitem",
            name="entry_type",
            field=models.CharField(
                choices=[("sale", "판매"), ("return", "반품"), ("payment", "결제")],
                db_index=True,
                default="sale",
                max_length=10,
                verbose_name="구분",
            ),
        ),
    ]
