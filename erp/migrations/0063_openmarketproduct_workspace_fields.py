from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("erp", "0062_marketplacesettlement_record_type")]
    operations = [
        migrations.AddField(model_name="openmarketproduct", name="workspace_status", field=models.CharField(choices=[("draft", "작성 중"), ("review", "검토 대기"), ("approved", "승인 완료"), ("uploaded", "업로드 완료")], db_index=True, default="draft", max_length=20, verbose_name="작업 상태")),
        migrations.AddField(model_name="openmarketproduct", name="target_channels", field=models.JSONField(blank=True, default=list, verbose_name="등록 대상 채널")),
        migrations.AddField(model_name="openmarketproduct", name="ai_instruction", field=models.TextField(blank=True, verbose_name="GPT 상품문구 작업 지시")),
        migrations.AddField(model_name="openmarketproduct", name="image_instruction", field=models.TextField(blank=True, verbose_name="이미지 수정 지시")),
    ]
