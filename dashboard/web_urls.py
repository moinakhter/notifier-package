"""Web URLs for dashboard."""
from django.urls import path
from .web_views import dashboard_home_view, dashboard_settings_view

urlpatterns = [
    path('', dashboard_home_view, name='dashboard-home'),
    path('settings/', dashboard_settings_view, name='dashboard-settings'),
]
