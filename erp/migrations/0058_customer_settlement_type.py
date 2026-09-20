from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("erp", "0057_purchaseentry_deduct_from_gold_balance")]

    operations = [
        migrations.AddField(
            model_name="customer",
            name="settlement_type",
            field=models.CharField(
                choices=[("account", "계좌 거래처"), ("cash", "현금 거래처")],
                default="account",
                max_length=10,
                verbose_name="정산 구분",
            ),
        ),
    ]
