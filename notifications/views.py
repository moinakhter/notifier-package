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
    Non-blocking endpoint for client applications on any server to ingest notifications.
    No authentication required by default. Clients can optionally authenticate
    via API Key header: X-API-Key: <key>
    Supports auto-creation and lookup of remote projects and servers.
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = NotificationIngestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # Determine or auto-register project from API key, slug, name, or UUID
        project = getattr(request, 'project', None)
        if not project:
            proj_identifier = (
                data.get('project')
                or data.get('project_name')
                or request.data.get('project')
                or request.data.get('project_name')
                or request.query_params.get('project')
            )
            if proj_identifier:
                proj_str = str(proj_identifier).strip()
                # 1. Try finding by UUID
                try:
                    import uuid as _uuid
                    _uuid.UUID(proj_str)
                    project = Project.objects.filter(id=proj_str).first()
                except (ValueError, AttributeError):
                    pass

                # 2. Try finding by slug or name
                if not project:
                    from django.utils.text import slugify
                    project = Project.objects.filter(slug=slugify(proj_str)).first()
                if not project:
                    project = Project.objects.filter(name__iexact=proj_str).first()

                # 3. Auto-create project for the remote application (thread-safe)
                if not project:
                    from projects.models import Environment
                    from django.db import IntegrityError
                    env_val = request.data.get('environment') or Environment.DEVELOPMENT
                    if env_val not in [e.value for e in Environment]:
                        env_val = Environment.DEVELOPMENT
                    try:
                        project, _ = Project.objects.get_or_create(
                            slug=slugify(proj_str),
                            defaults={
                                'name': proj_str,
                                'environment': env_val,
                                'description': f'Remote project auto-registered from host {data.get("server_hostname") or request.META.get("REMOTE_ADDR")}',
                            },
                        )
                    except IntegrityError:
                        project = Project.objects.filter(slug=slugify(proj_str)).first() or Project.objects.filter(name__iexact=proj_str).first()

            elif request.user.is_authenticated:
                project = Project.objects.filter(owner=request.user, is_active=True).first()

            if not project:
                project = Project.get_default_project()

        # Lookup or register server if hostname provided
        server = None
        server_hostname = (
            data.get('server_hostname')
            or request.data.get('hostname')
            or request.data.get('server')
        )
        server_ip = data.get('server_ip') or request.META.get('REMOTE_ADDR')
        if server_hostname:
            server, created = Server.objects.get_or_create(
                project=project,
                hostname=str(server_hostname).strip(),
                defaults={
                    'name': str(server_hostname).strip(),
                    'ip_address': server_ip if server_ip and server_ip != '127.0.0.1' else None,
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


class BatchNotificationIngestView(APIView):
    """
    High-throughput batch ingestion endpoint capable of absorbing
    thousands of log events per second from any microservice cluster.
    Accepts:
      {"events": [...], "project": "name", "server_hostname": "..."}
      or a raw JSON array: [{...}, {...}]
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request, *args, **kwargs):
        import time
        from projects.models import Environment
        data = request.data
        if isinstance(data, list):
            items = data
            project_name = request.query_params.get('project') or 'default-project'
            server_hostname = request.query_params.get('server_hostname') or 'remote-cluster'
        else:
            items = data.get('events') or data.get('logs') or data.get('items') or []
            project_name = data.get('project') or data.get('project_name') or 'default-project'
            server_hostname = data.get('server_hostname') or data.get('hostname') or 'remote-cluster'

        if not items:
            return Response({'error': 'No events provided in batch.'}, status=status.HTTP_400_BAD_REQUEST)

        # Lookup or register project and server
        project = getattr(request, 'project', None)
        if not project:
            from django.utils.text import slugify
            from django.db import IntegrityError
            project = Project.objects.filter(slug=slugify(project_name)).first()
            if not project:
                try:
                    project, _ = Project.objects.get_or_create(
                        slug=slugify(project_name),
                        defaults={
                            'name': project_name,
                            'environment': Environment.DEVELOPMENT,
                            'description': 'Batch ingest remote project',
                        },
                    )
                except IntegrityError:
                    project = Project.objects.filter(slug=slugify(project_name)).first()

        server = None
        if server_hostname:
            server, _ = Server.objects.get_or_create(
                project=project,
                hostname=str(server_hostname).strip(),
                defaults={'name': str(server_hostname).strip(), 'environment': project.environment},
            )
            server.touch()

        start_time = time.time()
        result = IngestionPipeline.process_batch(project, items, server=server)
        elapsed_sec = max(time.time() - start_time, 0.0001)
        elapsed_ms = round(elapsed_sec * 1000, 2)

        return Response({
            'status': 'accepted',
            'processed': result['processed'],
            'queued_for_delivery': result['queued'],
            'duration_ms': elapsed_ms,
            'throughput_per_sec': round(result['processed'] / elapsed_sec, 1),
        }, status=status.HTTP_202_ACCEPTED)


class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Search and filter notification history. View full tracebacks and delivery attempts.
    Acknowledge and resolve errors. Export filtered records.
    No authentication required by default.
    """
    permission_classes = [permissions.AllowAny]
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
        if user.is_authenticated and not (user.is_staff or user.is_superuser):
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
        """Mark notification as acknowledged."""
        notif = self.get_object()
        user = request.user if request.user.is_authenticated else None
        notif.acknowledge(user=user)
        return Response({
            'status': 'success',
            'message': 'Notification acknowledged.',
            'is_acknowledged': notif.is_acknowledged,
            'acknowledged_at': notif.acknowledged_at,
            'acknowledged_by': user.username if user else 'anonymous',
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def resolve(self, request, pk=None):
        """Mark notification as resolved with an optional resolution note."""
        notif = self.get_object()
        serializer = NotificationResolveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        note = serializer.validated_data.get('note', '')

        user = request.user if request.user.is_authenticated else None
        notif.resolve(user=user, note=note)
        return Response({
            'status': 'success',
            'message': 'Notification resolved.',
            'is_resolved': notif.is_resolved,
            'resolved_at': notif.resolved_at,
            'resolved_by': user.username if user else 'anonymous',
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
    permission_classes = [permissions.AllowAny]
    filter_backends = [DjangoFilterBackend, SearchFilter]
    filterset_fields = ['project', 'severity', 'is_active']
    search_fields = ['name', 'title_template', 'message_template']

    def get_queryset(self):
        user = self.request.user
        qs = NotificationTemplate.objects.select_related('project')
        if user.is_authenticated and not (user.is_staff or user.is_superuser):
            return qs.filter(models.Q(project__owner=user) | models.Q(project__owner__isnull=True))
        return qs


class RoutingRuleViewSet(viewsets.ModelViewSet):
    """CRUD viewset for custom notification routing rules."""
    serializer_class = RoutingRuleSerializer
    permission_classes = [permissions.AllowAny]
    filter_backends = [DjangoFilterBackend, SearchFilter]
    filterset_fields = ['project', 'severity', 'is_active']
    search_fields = ['name', 'description', 'service_name_pattern', 'title_pattern']

    def get_queryset(self):
        user = self.request.user
        qs = RoutingRule.objects.select_related('project')
        if user.is_authenticated and not (user.is_staff or user.is_superuser):
            return qs.filter(models.Q(project__owner=user) | models.Q(project__owner__isnull=True))
        return qs


class SeverityChannelSettingViewSet(viewsets.ModelViewSet):
    """CRUD viewset for project-wide channel enable/disable per severity."""
    serializer_class = SeverityChannelSettingSerializer
    permission_classes = [permissions.AllowAny]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['project', 'severity']

    def get_queryset(self):
        user = self.request.user
        qs = SeverityChannelSetting.objects.select_related('project')
        if user.is_authenticated and not (user.is_staff or user.is_superuser):
            return qs.filter(models.Q(project__owner=user) | models.Q(project__owner__isnull=True))
        return qs

    @action(detail=False, methods=['get', 'post'], url_path='project-matrix')
    def project_matrix(self, request):
        """
        Get or batch update all 5 severity channel configurations for a project at once.
        GET: /api/v1/notifications/severity-settings/project-matrix/?project=<id_or_slug>
        POST: /api/v1/notifications/severity-settings/project-matrix/
              {
                "project": "<id_or_slug>",
                "notify_exceptions_only": true,
                "settings": [
                    {"severity": "CRITICAL", "email_enabled": true, "telegram_enabled": true, "whatsapp_enabled": false, "instagram_enabled": false},
                    {"severity": "ERROR", "email_enabled": true, "telegram_enabled": false, "whatsapp_enabled": false, "instagram_enabled": false},
                    {"severity": "WARNING", "email_enabled": false, "telegram_enabled": false, "whatsapp_enabled": false, "instagram_enabled": false},
                    {"severity": "INFO", "email_enabled": false, "telegram_enabled": false, "whatsapp_enabled": false, "instagram_enabled": false},
                    {"severity": "SUCCESS", "email_enabled": false, "telegram_enabled": false, "whatsapp_enabled": false, "instagram_enabled": false}
                ]
              }
        """
        proj_identifier = request.data.get('project') or request.query_params.get('project')
        project = None
        if proj_identifier:
            proj_str = str(proj_identifier).strip()
            try:
                import uuid as _uuid
                _uuid.UUID(proj_str)
                project = Project.objects.filter(id=proj_str).first()
            except (ValueError, AttributeError):
                pass
            if not project:
                project = Project.objects.filter(slug=proj_str).first() or Project.objects.filter(name__iexact=proj_str).first()

        if not project:
            project = Project.get_default_project()

        if request.method == 'POST':
            if 'notify_exceptions_only' in request.data:
                project.notify_exceptions_only = bool(request.data['notify_exceptions_only'])
                project.save(update_fields=['notify_exceptions_only', 'updated_at'])

            settings_data = request.data.get('settings', [])
            for item in settings_data:
                sev = str(item.get('severity', '')).upper()
                if sev in [s.value for s in Severity]:
                    SeverityChannelSetting.objects.update_or_create(
                        project=project,
                        severity=sev,
                        defaults={
                            'email_enabled': bool(item.get('email_enabled', False)),
                            'telegram_enabled': bool(item.get('telegram_enabled', False)),
                            'whatsapp_enabled': bool(item.get('whatsapp_enabled', False)),
                            'instagram_enabled': bool(item.get('instagram_enabled', False)),
                        },
                    )

        # Ensure matrix exists
        matrix = project.get_or_create_severity_settings()
        serializer = SeverityChannelSettingSerializer(matrix, many=True)
        return Response({
            'project_id': str(project.id),
            'project_name': project.name,
            'notify_exceptions_only': project.notify_exceptions_only,
            'settings': serializer.data,
        })
