from io import BytesIO
from pathlib import Path

from django.core.files.base import ContentFile
from django.db import models
from django.db.models.signals import pre_save
from django.dispatch import receiver
from PIL import Image, ImageOps, UnidentifiedImageError


MAX_IMAGE_EDGE = 1600
JPEG_QUALITY = 82
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def optimize_uploaded_image(uploaded_file):
    """Resize and recompress a newly uploaded image; PDFs and animated GIFs stay untouched."""
    suffix = Path(uploaded_file.name or "").suffix.lower()
    if suffix not in IMAGE_SUFFIXES:
        return None
    try:
        uploaded_file.seek(0)
        with Image.open(uploaded_file) as source:
            if getattr(source, "is_animated", False) and suffix in {".gif", ".webp"}:
                return None
            source.seek(0)
            image = ImageOps.exif_transpose(source)
            image.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE), Image.Resampling.LANCZOS)
            has_alpha = image.mode in ("RGBA", "LA") or (
                image.mode == "P" and "transparency" in image.info
            )
            output = BytesIO()
            if has_alpha:
                image.convert("RGBA").save(output, format="PNG", optimize=True)
                extension = ".png"
            else:
                image.convert("RGB").save(
                    output, format="JPEG", quality=JPEG_QUALITY,
                    optimize=True, progressive=True,
                )
                extension = ".jpg"
            stem = Path(uploaded_file.name).stem or "image"
            return f"{stem}{extension}", output.getvalue()
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
        try:
            uploaded_file.seek(0)
        except (OSError, ValueError):
            pass
        return None


@receiver(pre_save, dispatch_uid="erp.optimize_uploaded_images")
def optimize_model_file_fields(sender, instance, **kwargs):
    if getattr(sender._meta, "app_label", None) != "erp":
        return
    for field in sender._meta.fields:
        if not isinstance(field, models.FileField):
            continue
        field_file = getattr(instance, field.name, None)
        if not field_file or getattr(field_file, "_committed", True):
            continue
        optimized = optimize_uploaded_image(field_file.file)
        if optimized is None:
            continue
        filename, content = optimized
        field_file.save(filename, ContentFile(content), save=False)
