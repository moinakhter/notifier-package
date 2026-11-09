"""Web URLs for dashboard."""
from django.urls import path
from .web_views import dashboard_home_view

urlpatterns = [
    path('', dashboard_home_view, name='dashboard-home'),
]
