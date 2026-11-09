"""Web views for rendering the browser-based dashboard UI."""
from datetime import timedelta
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.utils import timezone

from notifications.models import Notification, Severity, NotificationStatus
from delivery.models import DeliveryAttempt, DeliveryStatus
from projects.models import Project, Server


def dashboard_home_view(request):
    """Render the main dashboard overview page."""
    user = request.user
    now = timezone.now()
    day_ago = now - timedelta(days=1)

    notif_qs = Notification.objects.all()
    delivery_qs = DeliveryAttempt.objects.all()
    proj_qs = Project.objects.all()
    server_qs = Server.objects.all()

    if user.is_authenticated and not (user.is_staff or user.is_superuser):
        notif_qs = notif_qs.filter(project__owner=user)
        delivery_qs = delivery_qs.filter(notification__project__owner=user)
        proj_qs = proj_qs.filter(owner=user)
        server_qs = server_qs.filter(project__owner=user)

    total_notifications = notif_qs.count()
    critical_errors_total = notif_qs.filter(severity=Severity.CRITICAL.value).count()
    critical_errors_unresolved = notif_qs.filter(
        severity=Severity.CRITICAL.value,
        is_resolved=False,
    ).count()

    # Delivery stats
    delivery_total = delivery_qs.count()
    delivery_success = delivery_qs.filter(status=DeliveryStatus.DELIVERED.value).count()
    delivery_failed = delivery_qs.filter(status__in=[DeliveryStatus.FAILED.value, DeliveryStatus.DEAD_LETTER.value]).count()
    success_rate = round((delivery_success / delivery_total) * 100, 1) if delivery_total > 0 else 100.0

    # Errors by project
    errors_by_project = list(
        notif_qs.filter(severity__in=[Severity.ERROR.value, Severity.CRITICAL.value])
        .values('project__name', 'project__environment')
        .annotate(error_count=Count('id'))
        .order_by('-error_count')[:5]
    )

    # Errors by server
    errors_by_server = list(
        notif_qs.filter(server__isnull=False, severity__in=[Severity.ERROR.value, Severity.CRITICAL.value])
        .values('server__name', 'server__hostname')
        .annotate(error_count=Count('id'))
        .order_by('-error_count')[:5]
    )

    recent_activity = notif_qs.select_related('project', 'server').order_by('-created_at')[:20]

    context = {
        'total_notifications': total_notifications,
        'critical_errors_total': critical_errors_total,
        'critical_errors_unresolved': critical_errors_unresolved,
        'delivery_total': delivery_total,
        'delivery_success': delivery_success,
        'delivery_failed': delivery_failed,
        'success_rate': success_rate,
        'errors_by_project': errors_by_project,
        'errors_by_server': errors_by_server,
        'recent_activity': recent_activity,
        'projects': proj_qs,
    }
    return render(request, 'dashboard/index.html', context)
