from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("erp", "0069_openmarketchanneloption_external_item_id_and_more")]

    operations = [
        migrations.AddField(
            model_name="openmarketchannelsetting",
            name="category_name",
            field=models.CharField(blank=True, max_length=500, verbose_name="채널 카테고리 경로"),
        ),
    ]
