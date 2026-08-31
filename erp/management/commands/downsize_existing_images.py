import os
from io import BytesIO
from pathlib import Path
from tempfile import NamedTemporaryFile

from django.conf import settings
from django.core.management.base import BaseCommand
from PIL import Image, ImageOps, UnidentifiedImageError

from erp.image_processing import JPEG_QUALITY, MAX_IMAGE_EDGE


SUPPORTED = {".jpg", ".jpeg", ".png", ".webp"}


def compact_size(size_bytes):
    return f"{size_bytes / 1024 / 1024:.2f}MB"


class Command(BaseCommand):
    help = "Downsize existing ERP media images in place while preserving filenames and formats."

    def handle(self, *args, **options):
        media_root = Path(settings.MEDIA_ROOT).resolve()
        base_dir = Path(settings.BASE_DIR).resolve()
        if media_root == base_dir or base_dir not in media_root.parents:
            raise RuntimeError(f"Unsafe MEDIA_ROOT: {media_root}")

        scanned = changed = skipped = failed = 0
        before_bytes = after_bytes = 0
        for path in media_root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in SUPPORTED:
                continue
            scanned += 1
            original_size = path.stat().st_size
            before_bytes += original_size
            temporary_name = None
            try:
                with Image.open(path) as source:
                    suffix = path.suffix.lower()
                    if getattr(source, "is_animated", False) and suffix in {".gif", ".webp"}:
                        skipped += 1
                        after_bytes += original_size
                        continue
                    source.seek(0)
                    image = ImageOps.exif_transpose(source)
                    original_dimensions = image.size
                    if max(original_dimensions) <= MAX_IMAGE_EDGE:
                        skipped += 1
                        after_bytes += original_size
                        continue
                    image.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE), Image.Resampling.LANCZOS)
                    output = BytesIO()
                    if suffix in {".jpg", ".jpeg"}:
                        image.convert("RGB").save(
                            output, format="JPEG", quality=JPEG_QUALITY,
                            optimize=True, progressive=True,
                        )
                    elif suffix == ".png":
                        mode = "RGBA" if image.mode in ("RGBA", "LA") or "transparency" in image.info else "RGB"
                        image.convert(mode).save(output, format="PNG", optimize=True)
                    else:
                        mode = "RGBA" if image.mode in ("RGBA", "LA") else "RGB"
                        image.convert(mode).save(output, format="WEBP", quality=JPEG_QUALITY, method=6)

                optimized = output.getvalue()
                if image.size == original_dimensions and len(optimized) >= original_size:
                    skipped += 1
                    after_bytes += original_size
                    continue
                with NamedTemporaryFile(delete=False, dir=path.parent, suffix=path.suffix) as temporary:
                    temporary.write(optimized)
                    temporary_name = temporary.name
                os.replace(temporary_name, path)
                temporary_name = None
                changed += 1
                after_bytes += len(optimized)
                self.stdout.write(f"{path.relative_to(media_root)}: {original_dimensions} -> {image.size}")
            except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
                failed += 1
                after_bytes += original_size
                self.stderr.write(f"FAILED {path.relative_to(media_root)}: {exc}")
            finally:
                if temporary_name:
                    try:
                        os.unlink(temporary_name)
                    except OSError:
                        pass

        saved = max(before_bytes - after_bytes, 0)
        self.stdout.write(self.style.SUCCESS(
            f"scanned={scanned} changed={changed} skipped={skipped} failed={failed} "
            f"before={compact_size(before_bytes)} after={compact_size(after_bytes)} "
            f"saved={compact_size(saved)}"
        ))
