from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("erp", "0034_product_deleted_at_product_is_deleted")]

    operations = [
        migrations.AddField(
            model_name="companyprofile",
            name="weight_decimal_places",
            field=models.PositiveSmallIntegerField(
                choices=[(0, "0자리"), (1, "1자리"), (2, "2자리"), (3, "3자리")],
                default=2,
                help_text="판매관리와 각 현황표의 중량을 표시할 자릿수입니다. 다음 자리에서 반올림합니다.",
                verbose_name="중량 표시 소수점",
            ),
        ),
    ]
