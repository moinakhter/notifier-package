"""API views for dashboard statistics and metrics aggregation."""
from datetime import timedelta
from django.db.models import Count, Q
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import permissions

from notifications.models import Notification, Severity, NotificationStatus
from delivery.models import DeliveryAttempt, DeliveryStatus
from projects.models import Project, Server


class DashboardStatsView(APIView):
    """
    Consolidated dashboard statistics API providing:
      - Total notifications (all-time, last 24h, last 7d)
      - Critical errors count & unresolved criticals
      - Errors by project and server
      - Notification delivery success vs failure rates
      - Recent activity feed
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request, *args, **kwargs):
        user = request.user
        now = timezone.now()
        day_ago = now - timedelta(days=1)
        week_ago = now - timedelta(days=7)

        # Base querysets
        notif_qs = Notification.objects.all()
        delivery_qs = DeliveryAttempt.objects.all()
        proj_qs = Project.objects.all()
        server_qs = Server.objects.all()

        if user.is_authenticated and not (user.is_staff or user.is_superuser):
            notif_qs = notif_qs.filter(project__owner=user)
            delivery_qs = delivery_qs.filter(notification__project__owner=user)
            proj_qs = proj_qs.filter(owner=user)
            server_qs = server_qs.filter(project__owner=user)

        # Optional project filter from query param
        project_id = request.query_params.get('project_id')
        if project_id:
            notif_qs = notif_qs.filter(project_id=project_id)
            delivery_qs = delivery_qs.filter(notification__project_id=project_id)
            server_qs = server_qs.filter(project_id=project_id)

        # 1. Total Notifications Metrics
        total_notifications = notif_qs.count()
        notifications_24h = notif_qs.filter(created_at__gte=day_ago).count()
        notifications_7d = notif_qs.filter(created_at__gte=week_ago).count()

        # Severity breakdown
        severity_counts = {
            s.value: notif_qs.filter(severity=s.value).count()
            for s in Severity
        }

        # 2. Critical Errors Metrics
        critical_errors_total = severity_counts.get(Severity.CRITICAL.value, 0)
        critical_errors_unresolved = notif_qs.filter(
            severity=Severity.CRITICAL.value,
            is_resolved=False,
        ).count()
        critical_errors_24h = notif_qs.filter(
            severity=Severity.CRITICAL.value,
            created_at__gte=day_ago,
        ).count()

        # 3. Errors by Project & Server Breakdown
        errors_by_project = list(
            notif_qs.filter(severity__in=[Severity.ERROR.value, Severity.CRITICAL.value])
            .values('project__id', 'project__name', 'project__environment')
            .annotate(
                error_count=Count('id'),
                critical_count=Count('id', filter=Q(severity=Severity.CRITICAL.value)),
                unresolved_count=Count('id', filter=Q(is_resolved=False)),
            )
            .order_by('-error_count')[:10]
        )

        errors_by_server = list(
            notif_qs.filter(
                server__isnull=False,
                severity__in=[Severity.ERROR.value, Severity.CRITICAL.value],
            )
            .values('server__id', 'server__name', 'server__hostname', 'project__name')
            .annotate(
                error_count=Count('id'),
                critical_count=Count('id', filter=Q(severity=Severity.CRITICAL.value)),
            )
            .order_by('-error_count')[:10]
        )

        # 4. Delivery Success vs Failure Breakdown
        delivery_total = delivery_qs.count()
        delivery_success = delivery_qs.filter(status=DeliveryStatus.DELIVERED.value).count()
        delivery_failed = delivery_qs.filter(status__in=[DeliveryStatus.FAILED.value, DeliveryStatus.DEAD_LETTER.value]).count()
        delivery_retrying = delivery_qs.filter(status=DeliveryStatus.RETRYING.value).count()

        success_rate = (
            round((delivery_success / delivery_total) * 100, 1)
            if delivery_total > 0
            else 100.0
        )

        channel_breakdown = list(
            delivery_qs.values('channel')
            .annotate(
                total=Count('id'),
                delivered=Count('id', filter=Q(status=DeliveryStatus.DELIVERED.value)),
                failed=Count('id', filter=Q(status__in=[DeliveryStatus.FAILED.value, DeliveryStatus.DEAD_LETTER.value])),
            )
            .order_by('channel')
        )

        # 5. Recent Activity Feed
        recent_notifications = list(
            notif_qs.select_related('project', 'server')
            .order_by('-created_at')[:15]
            .values(
                'id',
                'title',
                'severity',
                'status',
                'service_name',
                'project__name',
                'server__hostname',
                'occurrence_count',
                'is_acknowledged',
                'is_resolved',
                'created_at',
            )
        )

        return Response({
            'overview': {
                'total_notifications': total_notifications,
                'notifications_24h': notifications_24h,
                'notifications_7d': notifications_7d,
                'total_projects': proj_qs.count(),
                'total_servers': server_qs.count(),
            },
            'critical_errors': {
                'total': critical_errors_total,
                'unresolved': critical_errors_unresolved,
                'last_24h': critical_errors_24h,
            },
            'severities': severity_counts,
            'errors_by_project': errors_by_project,
            'errors_by_server': errors_by_server,
            'delivery': {
                'total_attempts': delivery_total,
                'successful': delivery_success,
                'failed': delivery_failed,
                'retrying': delivery_retrying,
                'success_rate_percent': success_rate,
                'by_channel': channel_breakdown,
            },
            'recent_activity': recent_notifications,
        })
