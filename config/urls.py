from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.auth.decorators import login_required
from django.views.static import serve as media_serve
from django.urls import re_path
from .views import ERPLoginView, access_management, basic_management_login, initial_admin_setup

urlpatterns = [
    path("login/", ERPLoginView.as_view(), name="login"),
    path("basic-management/login/", basic_management_login, name="basic_management_login"),
    path("access-management/", access_management, name="access_management"),
    path("setup/", initial_admin_setup, name="initial_admin_setup"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("admin/", admin.site.urls),
    path("", include("erp.urls")),
]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
else:
    # 사진과 전표는 인증된 ERP 사용자에게만 제공합니다.
    urlpatterns += [
        re_path(r"^media/(?P<path>.*)$", login_required(media_serve), {"document_root": settings.MEDIA_ROOT}),
    ]
