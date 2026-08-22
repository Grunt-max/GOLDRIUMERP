from .models import CompanyProfile


def erp_number_settings(request):
    profile = CompanyProfile.objects.filter(singleton_key="default").only("weight_decimal_places").first()
    return {"weight_decimal_places": profile.weight_decimal_places if profile else 2}
