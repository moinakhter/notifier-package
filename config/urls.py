"""URL configuration for Notifier Service."""
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/v1/projects/', include('projects.urls')),
    path('api/v1/notifications/', include('notifications.urls')),
    path('api/v1/channels/', include('channels_config.urls')),
    path('api/v1/delivery/', include('delivery.urls')),
    path('api/v1/dashboard/', include('dashboard.urls')),
    path('', include('dashboard.web_urls')),
]
