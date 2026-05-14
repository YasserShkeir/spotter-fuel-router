from django.urls import path

from . import views

urlpatterns = [
    path("route/", views.plan_route, name="plan-route"),
    path("geocode/", views.geocode_search, name="geocode-search"),
]
