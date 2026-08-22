from functools import wraps
from urllib.parse import urlencode

from django.http import HttpResponseForbidden
from django.shortcuts import redirect
from django.urls import reverse

from config.views import MASTER_USERNAME


def master_reauthentication_required(view_func):
    """Protect basic-management pages and mutations with step-up authentication."""
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if request.user.username != MASTER_USERNAME:
            return HttpResponseForbidden("기초관리는 master 계정만 이용할 수 있습니다.")
        if request.session.get("basic_management_verified_user_id") != request.user.pk:
            query = urlencode({"next": request.get_full_path()})
            return redirect(f"{reverse('basic_management_login')}?{query}")
        return view_func(request, *args, **kwargs)
    return wrapped
