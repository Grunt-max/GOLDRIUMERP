from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("erp", "0017_sales_total_weight_and_colors")]

    operations = [
        migrations.AddField(
            model_name="saleitem", name="is_deleted",
            field=models.BooleanField(db_index=True, default=False, verbose_name="삭제"),
        ),
    ]
