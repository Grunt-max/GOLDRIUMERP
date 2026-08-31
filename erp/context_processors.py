import time
import shutil
from pathlib import Path
from django.urls import reverse

from django.conf import settings
from .models import CompanyProfile
from .access import allowed_sections_for
from config.views import MASTER_USERNAME


_storage_cache = {"checked_at": 0.0, "value": None}


def _format_storage_size(size_bytes):
    if size_bytes >= 1024 ** 3:
        return f"{size_bytes / 1024 ** 3:.2f}GB"
    if size_bytes >= 1024 ** 2:
        return f"{size_bytes / 1024 ** 2:.1f}MB"
    return f"{size_bytes / 1024:.1f}KB"


def _path_size(path):
    path = Path(path)
    if not path.exists():
        return 0
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    try:
        for item in path.rglob("*"):
            if item.is_file():
                try:
                    total += item.stat().st_size
                except OSError:
                    continue
    except OSError:
        pass
    return total


def _erp_storage_usage():
    """Return SQLite and uploaded-media sizes, cached to avoid scanning photos per request."""
    now = time.monotonic()
    if _storage_cache["value"] is not None and now - _storage_cache["checked_at"] < 30:
        return _storage_cache["value"]

    database_name = settings.DATABASES["default"].get("NAME")
    database_bytes = 0
    if database_name and settings.DATABASES["default"].get("ENGINE", "").endswith("sqlite3"):
        database_path = Path(database_name)
        database_bytes = sum(
            _path_size(Path(f"{database_path}{suffix}"))
            for suffix in ("", "-wal", "-shm")
        )
    media_bytes = _path_size(settings.MEDIA_ROOT)
    disk_target = Path(database_name).parent if database_name else settings.BASE_DIR
    try:
        disk_total, disk_used, disk_free = shutil.disk_usage(disk_target)
    except OSError:
        disk_total = disk_used = disk_free = 0
    value = {
        "total": _format_storage_size(database_bytes + media_bytes),
        "database": _format_storage_size(database_bytes),
        "media": _format_storage_size(media_bytes),
        "disk_used": _format_storage_size(disk_used),
        "disk_total": _format_storage_size(disk_total),
        "disk_free": _format_storage_size(disk_free),
    }
    _storage_cache.update(checked_at=now, value=value)
    return value


def erp_number_settings(request):
    profile = CompanyProfile.objects.filter(singleton_key="default").only("weight_decimal_places").first()
    allowed = allowed_sections_for(request.user)
    home_routes = (
        ("dashboard", "erp:dashboard"), ("gold_prices", "erp:gold_price_list"),
        ("orders", "erp:order_list"), ("activities", "erp:daily_activity_list"),
        ("gold_ledger", "erp:gold_ledger_list"), ("purchases", "erp:purchase_list"),
        ("sales", "erp:sales_list"), ("customers", "erp:customer_list"),
        ("products", "erp:product_list"), ("marketplaces", "erp:marketplace_list"),
    )
    home_url = next((reverse(route) for section, route in home_routes if section in allowed), reverse("login"))
    return {
        "weight_decimal_places": profile.weight_decimal_places if profile else 2,
        "erp_storage": _erp_storage_usage(),
        "erp_allowed_sections": allowed,
        "erp_is_master": request.user.is_authenticated and request.user.username == MASTER_USERNAME,
        "erp_home_url": home_url,
    }
