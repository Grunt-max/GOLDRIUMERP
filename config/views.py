from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, get_user_model, login, update_session_auth_hash
from django.contrib.auth.decorators import login_not_required
from django.contrib.auth.forms import PasswordChangeForm, SetPasswordForm, UserCreationForm
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

    def get_success_url(self):
        if self.request.user.username == MASTER_USERNAME:
            return super().get_success_url()
        from erp.access import allowed_sections_for
        first_routes = {
            "dashboard": "erp:dashboard", "gold_prices": "erp:gold_price_list", "orders": "erp:order_list",
            "activities": "erp:daily_activity_list", "gold_ledger": "erp:gold_ledger_list",
            "purchases": "erp:purchase_list", "sales": "erp:sales_list", "customers": "erp:customer_list",
            "products": "erp:product_list", "marketplaces": "erp:marketplace_list",
        }
        allowed = allowed_sections_for(self.request.user)
        for section, route in first_routes.items():
            if section in allowed:
                return reverse(route)
        return super().get_success_url()


def access_management(request):
    """Master-only employee account, view permission, and password management."""
    if request.user.username != MASTER_USERNAME:
        return HttpResponseForbidden("권한관리는 master 계정만 이용할 수 있습니다.")
    from erp.access import ERP_SECTIONS
    from erp.models import UserAccessProfile

    User = get_user_model()
    create_form = UserCreationForm(prefix="create")
    password_form = PasswordChangeForm(request.user, prefix="master")
    if request.method == "POST":
        action = request.POST.get("action")
        selected = [key for key, _label in ERP_SECTIONS if key in request.POST.getlist("sections")]
        if action == "create":
            create_form = UserCreationForm(request.POST, prefix="create")
            if create_form.is_valid():
                employee = create_form.save(commit=False)
                employee.is_staff = False
                employee.is_superuser = False
                employee.save()
                UserAccessProfile.objects.update_or_create(user=employee, defaults={"allowed_sections": selected})
                messages.success(request, f"{employee.username} 조회 계정을 만들었습니다.")
                return redirect("access_management")
        elif action == "update":
            employee = User.objects.filter(pk=request.POST.get("user_id")).exclude(username=MASTER_USERNAME).first()
            if employee is None:
                return HttpResponseForbidden("변경할 수 없는 계정입니다.")
            employee.is_active = request.POST.get("is_active") == "on"
            employee.is_staff = False
            employee.is_superuser = False
            employee.save(update_fields=["is_active", "is_staff", "is_superuser"])
            UserAccessProfile.objects.update_or_create(user=employee, defaults={"allowed_sections": selected})
            messages.success(request, f"{employee.username} 권한을 변경했습니다.")
            return redirect("access_management")
        elif action == "reset_password":
            employee = User.objects.filter(pk=request.POST.get("user_id")).exclude(username=MASTER_USERNAME).first()
            if employee is None:
                return HttpResponseForbidden("변경할 수 없는 계정입니다.")
            reset_form = SetPasswordForm(employee, request.POST)
            if reset_form.is_valid():
                reset_form.save()
                messages.success(request, f"{employee.username} 비밀번호를 변경했습니다.")
                return redirect("access_management")
            for errors in reset_form.errors.values():
                for error in errors:
                    messages.error(request, error)
        elif action == "master_password":
            password_form = PasswordChangeForm(request.user, request.POST, prefix="master")
            if password_form.is_valid():
                user = password_form.save()
                update_session_auth_hash(request, user)
                messages.success(request, "master 비밀번호를 변경했습니다.")
                return redirect("access_management")

    employees = []
    for employee in User.objects.exclude(username=MASTER_USERNAME).order_by("username"):
        profile, _created = UserAccessProfile.objects.get_or_create(user=employee)
        employees.append({"user": employee, "allowed": set(profile.allowed_sections)})
    return render(request, "registration/access_management.html", {
        "sections": ERP_SECTIONS, "employees": employees,
        "create_form": create_form, "password_form": password_form,
    })


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
