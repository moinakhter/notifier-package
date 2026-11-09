"""URLs for channels configuration."""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    EmailConfigurationViewSet,
    TelegramConfigurationViewSet,
    WhatsAppConfigurationViewSet,
    InstagramConfigurationViewSet,
)

router = DefaultRouter()
router.register(r'email', EmailConfigurationViewSet, basename='channel-email')
router.register(r'telegram', TelegramConfigurationViewSet, basename='channel-telegram')
router.register(r'whatsapp', WhatsAppConfigurationViewSet, basename='channel-whatsapp')
router.register(r'instagram', InstagramConfigurationViewSet, basename='channel-instagram')

urlpatterns = [
    path('', include(router.urls)),
]
