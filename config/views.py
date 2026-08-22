from django.conf import settings
from django.contrib.auth import authenticate, get_user_model, login
from django.contrib.auth.decorators import login_not_required
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.views import LoginView
from django.http import Http404, HttpResponseForbidden
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme


MASTER_USERNAME = "mykim9853"


class ERPLoginView(LoginView):
    template_name = "registration/login.html"
    redirect_authenticated_user = True

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["allow_initial_setup"] = settings.DEBUG and not get_user_model().objects.exists()
        return context


def basic_management_login(request):
    """Require the sole master account to confirm its password again."""
    if request.user.username != MASTER_USERNAME:
        return HttpResponseForbidden("기초관리는 master 계정만 이용할 수 있습니다.")

    next_url = request.POST.get("next") or request.GET.get("next") or reverse("erp:material_list")
    error = ""
    if request.method == "POST":
        password = request.POST.get("password", "")
        user = authenticate(request, username=request.user.username, password=password)
        if user is not None and user.pk == request.user.pk:
            request.session["basic_management_verified_user_id"] = user.pk
            if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
                next_url = reverse("erp:material_list")
            return redirect(next_url)
        error = "비밀번호가 올바르지 않습니다."

    return render(request, "registration/basic_management_login.html", {
        "next": next_url,
        "error": error,
    })


@login_not_required
def initial_admin_setup(request):
    if not settings.DEBUG or get_user_model().objects.exists():
        raise Http404
    form = UserCreationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save(commit=False)
        user.is_staff = True
        user.is_superuser = True
        user.save()
        login(request, user)
        return redirect("erp:dashboard")
    return render(request, "registration/initial_setup.html", {"form": form})
