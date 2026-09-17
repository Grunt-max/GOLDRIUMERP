from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("erp", "0056_salecustomerchangelog")]

    operations = [
        migrations.AddField(
            model_name="purchaseentry",
            name="deduct_from_gold_balance",
            field=models.BooleanField(db_index=True, default=False, verbose_name="우리 금 시제 자동 차감"),
        ),
    ]
