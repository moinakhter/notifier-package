"""Views for project and API key management."""
from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter

from .models import Project, APIKey, Server
from .serializers import (
    ProjectSerializer,
    ServerSerializer,
    APIKeySerializer,
    APIKeyCreateSerializer,
    APIKeyRotateSerializer,
)


class ProjectViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing projects across development, staging, and production.
    """
    serializer_class = ProjectSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['environment', 'is_active']
    search_fields = ['name', 'slug', 'description']
    ordering_fields = ['name', 'created_at']

    def get_queryset(self):
        user = self.request.user
        if user.is_staff or user.is_superuser:
            return Project.objects.all().prefetch_related('servers', 'api_keys')
        return Project.objects.filter(owner=user).prefetch_related('servers', 'api_keys')

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)


class ServerViewSet(viewsets.ModelViewSet):
    """
    ViewSet for registering and managing servers within projects.
    """
    serializer_class = ServerSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['project', 'environment', 'is_active']
    search_fields = ['name', 'hostname', 'ip_address']
    ordering_fields = ['name', 'created_at', 'last_seen_at']

    def get_queryset(self):
        user = self.request.user
        qs = Server.objects.select_related('project')
        if user.is_staff or user.is_superuser:
            return qs
        return qs.filter(project__owner=user)


class APIKeyViewSet(viewsets.ModelViewSet):
    """
    ViewSet for creating, listing, rotating, and revoking API keys.
    """
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['project', 'is_active']
    search_fields = ['name', 'prefix']
    ordering_fields = ['created_at', 'last_used_at']

    def get_serializer_class(self):
        if self.action == 'create':
            return APIKeyCreateSerializer
        if self.action == 'rotate':
            return APIKeyRotateSerializer
        return APIKeySerializer

    def get_queryset(self):
        user = self.request.user
        qs = APIKey.objects.select_related('project')
        if user.is_staff or user.is_superuser:
            return qs
        return qs.filter(project__owner=user)

    @action(detail=True, methods=['post'])
    def rotate(self, request, pk=None):
        """
        Rotate the API key: revoke existing key and issue a new one.
        Returns the raw new key once.
        """
        api_key = self.get_object()
        serializer = APIKeyRotateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        new_name = serializer.validated_data.get('new_name')
        new_key_obj, raw_key = api_key.rotate(new_name=new_name)

        return Response({
            'status': 'success',
            'message': 'API key rotated successfully. Store this key safely; it cannot be retrieved again.',
            'old_key_revoked': True,
            'new_key_id': str(new_key_obj.id),
            'prefix': new_key_obj.prefix,
            'name': new_key_obj.name,
            'raw_key': raw_key,
            'created_at': new_key_obj.created_at,
        }, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def revoke(self, request, pk=None):
        """
        Revoke an API key immediately.
        """
        api_key = self.get_object()
        if not api_key.is_active:
            return Response(
                {'status': 'info', 'message': 'API key is already revoked.'},
                status=status.HTTP_200_OK,
            )
        api_key.revoke()
        return Response({
            'status': 'success',
            'message': 'API key revoked successfully.',
            'revoked_at': api_key.revoked_at,
        }, status=status.HTTP_200_OK)
