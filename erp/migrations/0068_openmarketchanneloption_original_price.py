from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("erp", "0067_openmarketchanneloption")]

    operations = [
        migrations.AddField(
            model_name="openmarketchanneloption",
            name="original_price",
            field=models.DecimalField(
                blank=True, decimal_places=0,
                help_text="할인 전 정상가입니다. 비워 두면 판매가와 같게 전송합니다.",
                max_digits=14, null=True, verbose_name="정상가",
            ),
        ),
    ]
