from django.conf import settings
from django.db import migrations, models
import django.core.validators
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [("erp", "0025_dailyactivity_soft_delete_and_photos"), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.CreateModel(name="Factory", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("name", models.CharField(max_length=100, unique=True, verbose_name="공장명")),
            ("contact", models.CharField(blank=True, max_length=50, verbose_name="담당자")),
            ("phone", models.CharField(blank=True, max_length=30, verbose_name="연락처")),
            ("memo", models.CharField(blank=True, max_length=200, verbose_name="비고")),
            ("active", models.BooleanField(default=True, verbose_name="사용")),
            ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="등록일시")),
        ], options={"ordering": ["name"]}),
        migrations.CreateModel(name="GoldLedgerEntry", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("entry_date", models.DateField(db_index=True, default=django.utils.timezone.localdate, verbose_name="수불일")),
            ("entry_type", models.CharField(choices=[("issue", "금 불출"), ("receive", "금 회수"), ("gold_payment", "금 결제"), ("cash_payment", "현금 결제"), ("adjustment", "조정")], db_index=True, max_length=20, verbose_name="수불 구분")),
            ("actual_weight", models.DecimalField(decimal_places=3, default=0, max_digits=12, verbose_name="실제 중량(g)")),
            ("pure_gold_weight", models.DecimalField(decimal_places=3, default=0, max_digits=14, verbose_name="순금 환산중량(g)")),
            ("cash_amount", models.DecimalField(decimal_places=0, default=0, max_digits=14, verbose_name="현금 결제액")),
            ("reference_no", models.CharField(blank=True, max_length=30, verbose_name="관련번호")),
            ("memo", models.CharField(blank=True, max_length=200, verbose_name="비고")),
            ("image", models.FileField(blank=True, upload_to="gold-ledger/%Y/%m/", validators=[django.core.validators.FileExtensionValidator(["jpg", "jpeg", "png", "webp", "gif", "pdf"])], verbose_name="전표 사진")),
            ("is_deleted", models.BooleanField(db_index=True, default=False, verbose_name="삭제 여부")),
            ("deleted_at", models.DateTimeField(blank=True, null=True, verbose_name="삭제일시")),
            ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="등록일시")),
            ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL, verbose_name="작성자")),
            ("factory", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="ledger_entries", to="erp.factory", verbose_name="공장")),
            ("material", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to="erp.material", verbose_name="재질")),
        ], options={"ordering": ["-entry_date", "-id"]}),
    ]
