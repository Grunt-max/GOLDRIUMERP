from django.db import migrations


def separate_generated_and_manual_options(apps, schema_editor):
    ChannelOption = apps.get_model("erp", "OpenMarketChannelOption")
    ChannelSetting = apps.get_model("erp", "OpenMarketChannelSetting")
    ChannelOption.objects.filter(
        generated_from_common=True,
        external_option_id="",
        external_item_id="",
    ).exclude(
        setting__external_product_id="",
        setting__external_channel_product_id="",
    ).update(active=False)
    for setting in ChannelSetting.objects.filter(
        external_product_id="", external_channel_product_id="",
        selling_options__generated_from_common=True,
    ).distinct().iterator():
        ChannelOption.objects.filter(
            setting_id=setting.pk,
            generated_from_common=False,
            common_combination__isnull=True,
            external_option_id="",
            external_item_id="",
        ).update(active=False)


class Migration(migrations.Migration):

    dependencies = [
        ("erp", "0071_openmarketchanneloption_generated_from_common_and_more"),
    ]

    operations = [
        migrations.RunPython(separate_generated_and_manual_options, migrations.RunPython.noop),
    ]
