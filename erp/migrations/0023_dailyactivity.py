from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [
        ("erp", "0022_order_number_and_soft_delete"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name="DailyActivity",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("activity_date", models.DateField(db_index=True, default=django.utils.timezone.localdate, verbose_name="행적일")),
                ("content", models.TextField(max_length=1000, verbose_name="업무 내용")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="작성일시")),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="erp_daily_activities", to=settings.AUTH_USER_MODEL, verbose_name="작성자")),
            ],
            options={"ordering": ["-activity_date", "-created_at"]},
        ),
    ]
