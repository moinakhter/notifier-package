"""Views for notification ingestion, history, triage, templates, and routing rules."""
import csv
import io
import json
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import viewsets, permissions, status, renderers
from rest_framework.views import APIView
from rest_framework.decorators import action, renderer_classes
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter


class PassthroughRenderer(renderers.BaseRenderer):
    """Renderer that allows returning pre-formatted responses like CSV directly."""
    media_type = '*/*'
    format = 'csv'

    def render(self, data, accepted_media_type=None, renderer_context=None):
        if isinstance(data, (bytes, str)):
            return data
        return json.dumps(data, default=str)

from projects.models import Project, Server
from .models import (
    Notification,
    NotificationTemplate,
    RoutingRule,
    SeverityChannelSetting,
    NotificationStatus,
)
from .serializers import (
    NotificationIngestSerializer,
    NotificationListSerializer,
    NotificationDetailSerializer,
    NotificationAcknowledgeSerializer,
    NotificationResolveSerializer,
    NotificationTemplateSerializer,
    RoutingRuleSerializer,
    SeverityChannelSettingSerializer,
)
from .pipeline import IngestionPipeline


class NotificationIngestView(APIView):
    """
    Non-blocking endpoint for client applications to ingest notifications.
    Clients authenticate via API Key header:
      X-API-Key: <key>
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        serializer = NotificationIngestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # Determine project from API key auth or explicit query/body parameter
        project = getattr(request, 'project', None)
        if not project:
            project_id = request.data.get('project') or request.query_params.get('project')
            if project_id:
                project = Project.objects.filter(id=project_id, owner=request.user).first()
            if not project:
                # Default to first active project of the authenticated user
                project = Project.objects.filter(owner=request.user, is_active=True).first()

        if not project:
            return Response(
                {'error': 'No active project identified for this notification.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Lookup or register server if hostname provided
        server = None
        server_hostname = data.get('server_hostname')
        if server_hostname:
            server, created = Server.objects.get_or_create(
                project=project,
                hostname=server_hostname,
                defaults={
                    'name': server_hostname,
                    'environment': project.environment,
                },
            )
            server.touch()

        # Ingestion pipeline handles dedup, rate limit, grouping & async Celery queue
        notif, is_queued, action_summary = IngestionPipeline.process_notification(
            project=project,
            title=data['title'],
            message=data.get('message', ''),
            severity=data.get('severity'),
            server=server,
            service_name=data.get('service_name', ''),
            error_type=data.get('error_type', ''),
            traceback=data.get('traceback', ''),
            context=data.get('context', {}),
            idempotency_key=data.get('idempotency_key'),
            template_name=data.get('template_name'),
        )

        return Response({
            'status': notif.status,
            'notification_id': str(notif.id),
            'action': action_summary,
            'queued_for_delivery': is_queued,
            'occurrence_count': notif.occurrence_count,
            'created_at': notif.created_at,
        }, status=status.HTTP_202_ACCEPTED if is_queued else status.HTTP_200_OK)


class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Search and filter notification history. View full tracebacks and delivery attempts.
    Acknowledge and resolve errors. Export filtered records.
    """
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = [
        'project',
        'server',
        'service_name',
        'severity',
        'status',
        'is_acknowledged',
        'is_resolved',
    ]
    search_fields = ['title', 'message', 'service_name', 'error_type', 'traceback']
    ordering_fields = ['created_at', 'severity', 'status']

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return NotificationDetailSerializer
        return NotificationListSerializer

    def get_queryset(self):
        user = self.request.user
        qs = Notification.objects.select_related('project', 'server', 'acknowledged_by', 'resolved_by')
        if not (user.is_staff or user.is_superuser):
            qs = qs.filter(project__owner=user)

        # Date filtering
        start_date = self.request.query_params.get('start_date')
        end_date = self.request.query_params.get('end_date')
        if start_date:
            qs = qs.filter(created_at__gte=start_date)
        if end_date:
            qs = qs.filter(created_at__lte=end_date)

        return qs

    @action(detail=True, methods=['post'])
    def acknowledge(self, request, pk=None):
        """Mark notification as acknowledged by current user."""
        notif = self.get_object()
        notif.acknowledge(user=request.user)
        return Response({
            'status': 'success',
            'message': 'Notification acknowledged.',
            'is_acknowledged': notif.is_acknowledged,
            'acknowledged_at': notif.acknowledged_at,
            'acknowledged_by': request.user.username,
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def resolve(self, request, pk=None):
        """Mark notification as resolved with an optional resolution note."""
        notif = self.get_object()
        serializer = NotificationResolveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        note = serializer.validated_data.get('note', '')

        notif.resolve(user=request.user, note=note)
        return Response({
            'status': 'success',
            'message': 'Notification resolved.',
            'is_resolved': notif.is_resolved,
            'resolved_at': notif.resolved_at,
            'resolved_by': request.user.username,
            'resolution_note': notif.resolution_note,
        }, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'], renderer_classes=[renderers.JSONRenderer, PassthroughRenderer])
    def export(self, request, *args, **kwargs):
        """
        Export filtered notifications as CSV or JSON.
        Query params: ?format=csv (default) or ?format=json
        """
        queryset = self.filter_queryset(self.get_queryset())
        export_format = request.query_params.get('export_format') or request.query_params.get('format', 'csv')
        export_format = str(export_format).lower()

        if export_format == 'json':
            serializer = NotificationDetailSerializer(queryset[:1000], many=True)
            response = HttpResponse(
                json.dumps(serializer.data, indent=2, default=str),
                content_type='application/json',
            )
            response['Content-Disposition'] = 'attachment; filename="notifications_export.json"'
            return response

        # CSV Export
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            'ID',
            'Project',
            'Environment',
            'Server',
            'Severity',
            'Status',
            'Service',
            'Error Type',
            'Title',
            'Message',
            'Occurrences',
            'Acknowledged',
            'Resolved',
            'Created At',
        ])

        for n in queryset[:2000]:
            writer.writerow([
                str(n.id),
                n.project.name,
                n.project.environment,
                n.server.hostname if n.server else '',
                n.severity,
                n.status,
                n.service_name,
                n.error_type,
                n.title,
                n.message[:250].replace('\n', ' '),
                n.occurrence_count,
                n.is_acknowledged,
                n.is_resolved,
                n.created_at.isoformat(),
            ])

        response = HttpResponse(output.getvalue(), content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="notifications_{timezone.now().strftime("%Y%m%d_%H%M%S")}.csv"'
        return response


class NotificationTemplateViewSet(viewsets.ModelViewSet):
    """CRUD viewset for notification templates."""
    serializer_class = NotificationTemplateSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter]
    filterset_fields = ['project', 'severity', 'is_active']
    search_fields = ['name', 'title_template', 'message_template']

    def get_queryset(self):
        user = self.request.user
        qs = NotificationTemplate.objects.select_related('project')
        if user.is_staff or user.is_superuser:
            return qs
        return qs.filter(project__owner=user)


class RoutingRuleViewSet(viewsets.ModelViewSet):
    """CRUD viewset for custom notification routing rules."""
    serializer_class = RoutingRuleSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter]
    filterset_fields = ['project', 'severity', 'is_active']
    search_fields = ['name', 'description', 'service_name_pattern', 'title_pattern']

    def get_queryset(self):
        user = self.request.user
        qs = RoutingRule.objects.select_related('project')
        if user.is_staff or user.is_superuser:
            return qs
        return qs.filter(project__owner=user)


class SeverityChannelSettingViewSet(viewsets.ModelViewSet):
    """CRUD viewset for project-wide channel enable/disable per severity."""
    serializer_class = SeverityChannelSettingSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['project', 'severity']

    def get_queryset(self):
        user = self.request.user
        qs = SeverityChannelSetting.objects.select_related('project')
        if user.is_staff or user.is_superuser:
            return qs
        return qs.filter(project__owner=user)
