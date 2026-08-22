from django.core.validators import FileExtensionValidator
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("erp", "0014_product_image")]

    operations = [
        migrations.AlterField(
            model_name="order",
            name="status",
            field=models.CharField(
                choices=[("new", "접수"), ("partial", "부분출고"), ("done", "완료"), ("cancel", "취소")],
                default="new", max_length=10, verbose_name="상태",
            ),
        ),
        migrations.AddField(model_name="order", name="due_date", field=models.DateField(blank=True, db_index=True, null=True, verbose_name="정상 납기일")),
        migrations.AddField(
            model_name="order", name="source_type",
            field=models.CharField(choices=[("legacy", "기존자료"), ("quick", "빠른주문"), ("photo", "사진주문")], default="legacy", max_length=10, verbose_name="접수 방식"),
        ),
        migrations.AddField(
            model_name="order", name="order_image",
            field=models.FileField(blank=True, upload_to="orders/%Y/%m/", validators=[FileExtensionValidator(["jpg", "jpeg", "png", "webp", "gif"])], verbose_name="주문 사진"),
        ),
        migrations.AddField(model_name="order", name="raw_order_text", field=models.TextField(blank=True, verbose_name="빠른 주문 원문")),
        migrations.AddField(
            model_name="order", name="delivery_type",
            field=models.CharField(choices=[("finished", "완제품"), ("semi", "반제품")], default="finished", max_length=10, verbose_name="납품 형태"),
        ),
        migrations.AddField(model_name="order", name="color", field=models.CharField(blank=True, max_length=20, verbose_name="색상")),
        migrations.AddField(model_name="order", name="thickness_spec", field=models.CharField(blank=True, max_length=40, verbose_name="굵기")),
        migrations.AddField(model_name="order", name="length_spec", field=models.CharField(blank=True, max_length=40, verbose_name="길이")),
        migrations.AddField(model_name="order", name="option_detail", field=models.CharField(blank=True, max_length=200, verbose_name="장식·옵션")),
        migrations.AddField(model_name="order", name="fulfilled_quantity", field=models.PositiveIntegerField(default=0, verbose_name="출고수량")),
        migrations.AlterField(
            model_name="order", name="source_type",
            field=models.CharField(choices=[("legacy", "기존자료"), ("quick", "빠른주문"), ("photo", "사진주문")], default="quick", max_length=10, verbose_name="접수 방식"),
        ),
    ]
