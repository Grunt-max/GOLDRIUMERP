import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("erp", "0013_alter_saleitem_entry_type")]
    operations = [
        migrations.AddField(
            model_name="product",
            name="image",
            field=models.FileField(
                blank=True,
                upload_to="products/",
                validators=[django.core.validators.FileExtensionValidator(["jpg", "jpeg", "png", "webp", "gif"])],
                verbose_name="상품사진",
            ),
        ),
    ]
