from django.db import migrations, models
import django.core.validators


class Migration(migrations.Migration):
    dependencies = [("erp", "0023_dailyactivity")]
    operations = [
        migrations.AddField(
            model_name="dailyactivity", name="image",
            field=models.FileField(
                blank=True, upload_to="activities/%Y/%m/", verbose_name="첨부 사진",
                validators=[django.core.validators.FileExtensionValidator(["jpg", "jpeg", "png", "webp", "gif"])],
            ),
        ),
    ]
