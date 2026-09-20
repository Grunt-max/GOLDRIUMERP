from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("erp", "0063_openmarketproduct_workspace_fields")]
    operations = [
        migrations.AddField(
            model_name="openmarketproduct", name="pricing_material",
            field=models.CharField(choices=[("gold", "금 제품"), ("silver", "은 제품")], default="gold", max_length=10, verbose_name="가격 계산 재질"),
        ),
        migrations.AddField(
            model_name="openmarketproduct", name="silver_price_per_gram",
            field=models.DecimalField(decimal_places=0, default=0, max_digits=12, verbose_name="은 원가(원/g)"),
        ),
        migrations.AlterField(
            model_name="openmarketvariant", name="base_variant",
            field=models.CharField(choices=[("14KY", "14K 옐로우"), ("14KP", "14K 핑크"), ("18KY", "18K 옐로우"), ("18KP", "18K 핑크"), ("S925", "925 Silver"), ("ETC", "기타")], default="ETC", max_length=10, verbose_name="기본 변형"),
        ),
    ]
