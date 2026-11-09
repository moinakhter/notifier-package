"""Views for channel configuration and test connections."""
from django.db import models
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter

from .models import (
    EmailConfiguration,
    TelegramConfiguration,
    WhatsAppConfiguration,
    InstagramConfiguration,
)
from .serializers import (
    EmailConfigurationSerializer,
    TelegramConfigurationSerializer,
    WhatsAppConfigurationSerializer,
    InstagramConfigurationSerializer,
)
from .services import (
    EmailService,
    TelegramService,
    WhatsAppService,
    InstagramService,
)


class BaseChannelViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.AllowAny]
    filter_backends = [DjangoFilterBackend, SearchFilter]
    filterset_fields = ['project', 'is_active', 'is_verified']
    search_fields = ['name']

    def get_queryset(self):
        user = self.request.user
        qs = self.model.objects.select_related('project')
        if user.is_authenticated and not (user.is_staff or user.is_superuser):
            return qs.filter(models.Q(project__owner=user) | models.Q(project__owner__isnull=True))
        return qs


class EmailConfigurationViewSet(BaseChannelViewSet):
    model = EmailConfiguration
    queryset = EmailConfiguration.objects.all()
    serializer_class = EmailConfigurationSerializer

    @action(detail=True, methods=['post'])
    def test_connection(self, request, pk=None):
        config = self.get_object()
        success, message = EmailService.test_connection(config)
        config.mark_tested(success, message)
        return Response({
            'success': success,
            'message': message,
            'is_verified': config.is_verified,
            'last_tested_at': config.last_tested_at,
        }, status=status.HTTP_200_OK if success else status.HTTP_400_BAD_REQUEST)


class TelegramConfigurationViewSet(BaseChannelViewSet):
    model = TelegramConfiguration
    queryset = TelegramConfiguration.objects.all()
    serializer_class = TelegramConfigurationSerializer

    @action(detail=True, methods=['post'])
    def test_connection(self, request, pk=None):
        config = self.get_object()
        success, message = TelegramService.test_connection(config)
        config.mark_tested(success, message)
        return Response({
            'success': success,
            'message': message,
            'is_verified': config.is_verified,
            'last_tested_at': config.last_tested_at,
        }, status=status.HTTP_200_OK if success else status.HTTP_400_BAD_REQUEST)


class WhatsAppConfigurationViewSet(BaseChannelViewSet):
    model = WhatsAppConfiguration
    queryset = WhatsAppConfiguration.objects.all()
    serializer_class = WhatsAppConfigurationSerializer

    @action(detail=True, methods=['post'])
    def test_connection(self, request, pk=None):
        config = self.get_object()
        success, message = WhatsAppService.test_connection(config)
        config.mark_tested(success, message)
        return Response({
            'success': success,
            'message': message,
            'is_verified': config.is_verified,
            'last_tested_at': config.last_tested_at,
        }, status=status.HTTP_200_OK if success else status.HTTP_400_BAD_REQUEST)


class InstagramConfigurationViewSet(BaseChannelViewSet):
    model = InstagramConfiguration
    queryset = InstagramConfiguration.objects.all()
    serializer_class = InstagramConfigurationSerializer

    @action(detail=True, methods=['post'])
    def test_connection(self, request, pk=None):
        config = self.get_object()
        success, message = InstagramService.test_connection(config)
        config.mark_tested(success, message)
        return Response({
            'success': success,
            'message': message,
            'is_verified': config.is_verified,
            'last_tested_at': config.last_tested_at,
        }, status=status.HTTP_200_OK if success else status.HTTP_400_BAD_REQUEST)
