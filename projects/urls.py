"""URLs for projects app."""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import ProjectViewSet, ServerViewSet, APIKeyViewSet

router = DefaultRouter()
router.register(r'projects', ProjectViewSet, basename='project')
router.register(r'servers', ServerViewSet, basename='server')
router.register(r'api-keys', APIKeyViewSet, basename='apikey')

urlpatterns = [
    path('', include(router.urls)),
]
