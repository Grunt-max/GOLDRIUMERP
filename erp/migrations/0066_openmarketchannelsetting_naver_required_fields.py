from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("erp", "0065_openmarketchannelsetting_upload_tracking")]

    operations = [
        migrations.AddField(model_name="openmarketchannelsetting", name="naver_origin_status", field=models.CharField(choices=[("SUSPENSION", "판매 중지"), ("SALE", "판매 중")], default="SUSPENSION", max_length=20, verbose_name="네이버 판매 상태")),
        migrations.AddField(model_name="openmarketchannelsetting", name="naver_channel_display_status", field=models.CharField(choices=[("SUSPENSION", "전시 중지"), ("ON", "전시 중")], default="SUSPENSION", max_length=20, verbose_name="네이버 전시 상태")),
        migrations.AddField(model_name="openmarketchannelsetting", name="after_service_phone", field=models.CharField(blank=True, max_length=30, verbose_name="A/S 전화번호")),
        migrations.AddField(model_name="openmarketchannelsetting", name="after_service_guide", field=models.CharField(blank=True, max_length=500, verbose_name="A/S 안내")),
        migrations.AddField(model_name="openmarketchannelsetting", name="origin_area_code", field=models.CharField(choices=[("00", "국산"), ("01", "원양산"), ("02", "수입산"), ("03", "기타-상세 설명 표시"), ("04", "기타-직접 입력"), ("05", "표기 의무 대상 아님")], default="00", max_length=2, verbose_name="원산지")),
        migrations.AddField(model_name="openmarketchannelsetting", name="origin_area_content", field=models.CharField(blank=True, max_length=200, verbose_name="원산지 직접 입력")),
        migrations.AddField(model_name="openmarketchannelsetting", name="minor_purchasable", field=models.BooleanField(default=True, verbose_name="미성년자 구매 가능")),
    ]
