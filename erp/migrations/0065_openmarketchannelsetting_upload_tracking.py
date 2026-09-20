from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("erp", "0064_openmarketproduct_silver_pricing")]
    operations = [
        migrations.AddField(model_name="openmarketchannelsetting", name="external_product_id", field=models.CharField(blank=True, max_length=120, verbose_name="등록된 상품번호")),
        migrations.AddField(model_name="openmarketchannelsetting", name="upload_status", field=models.CharField(blank=True, max_length=30, verbose_name="업로드 상태")),
        migrations.AddField(model_name="openmarketchannelsetting", name="last_upload_error", field=models.TextField(blank=True, verbose_name="최근 업로드 오류")),
        migrations.AddField(model_name="openmarketchannelsetting", name="last_uploaded_at", field=models.DateTimeField(blank=True, null=True, verbose_name="최근 업로드 시각")),
    ]
