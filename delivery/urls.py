"""URLs for delivery app."""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import DeliveryAttemptViewSet, DeadLetterEntryViewSet

router = DefaultRouter()
router.register(r'attempts', DeliveryAttemptViewSet, basename='delivery-attempt')
router.register(r'dead-letter', DeadLetterEntryViewSet, basename='dead-letter')

urlpatterns = [
    path('', include(router.urls)),
]
