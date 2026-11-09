"""URLs for notifications app."""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    NotificationIngestView,
    BatchNotificationIngestView,
    NotificationViewSet,
    NotificationTemplateViewSet,
    RoutingRuleViewSet,
    SeverityChannelSettingViewSet,
)

router = DefaultRouter()
router.register(r'history', NotificationViewSet, basename='notification-history')
router.register(r'templates', NotificationTemplateViewSet, basename='notification-template')
router.register(r'routing-rules', RoutingRuleViewSet, basename='routing-rule')
router.register(r'severity-channels', SeverityChannelSettingViewSet, basename='severity-channel')

urlpatterns = [
    path('notify/', NotificationIngestView.as_view(), name='notification-notify'),
    path('batch/', BatchNotificationIngestView.as_view(), name='notification-batch'),
    path('', include(router.urls)),
]
