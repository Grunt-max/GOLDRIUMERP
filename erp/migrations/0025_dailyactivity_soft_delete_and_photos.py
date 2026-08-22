from django.db import migrations, models
import django.core.validators
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("erp", "0024_dailyactivity_image")]
    operations = [
        migrations.AddField(
            model_name="dailyactivity", name="is_deleted",
            field=models.BooleanField(db_index=True, default=False, verbose_name="삭제 여부"),
        ),
        migrations.AddField(
            model_name="dailyactivity", name="deleted_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="삭제일시"),
        ),
        migrations.CreateModel(
            name="DailyActivityPhoto",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("image", models.FileField(upload_to="activities/%Y/%m/", validators=[django.core.validators.FileExtensionValidator(["jpg", "jpeg", "png", "webp", "gif"])], verbose_name="사진")),
                ("uploaded_at", models.DateTimeField(auto_now_add=True, verbose_name="등록일시")),
                ("activity", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="photos", to="erp.dailyactivity", verbose_name="당일행적")),
            ],
            options={"ordering": ["id"]},
        ),
    ]
