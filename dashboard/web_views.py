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


def dashboard_settings_view(request):
    """Render and manage notification filtering and channel settings per project."""
    user = request.user
    proj_qs = Project.objects.all()
    if user.is_authenticated and not (user.is_staff or user.is_superuser):
        proj_qs = proj_qs.filter(owner=user)

    # Resolve active project
    proj_id = request.GET.get('project') or request.POST.get('project')
    selected_project = None
    if proj_id:
        selected_project = proj_qs.filter(id=proj_id).first()
    if not selected_project:
        selected_project = proj_qs.first() or Project.get_default_project()

    success_message = None

    if request.method == 'POST':
        # Update project settings
        selected_project.notify_exceptions_only = 'notify_exceptions_only' in request.POST
        selected_project.save(update_fields=['notify_exceptions_only', 'updated_at'])

        # Update per-severity channel settings
        from notifications.models import SeverityChannelSetting
        severities = [s.value for s in Severity]
        for sev in severities:
            email_key = f'email_{sev}'
            tg_key = f'telegram_{sev}'
            wa_key = f'whatsapp_{sev}'
            ig_key = f'instagram_{sev}'

            SeverityChannelSetting.objects.update_or_create(
                project=selected_project,
                severity=sev,
                defaults={
                    'email_enabled': email_key in request.POST,
                    'telegram_enabled': tg_key in request.POST,
                    'whatsapp_enabled': wa_key in request.POST,
                    'instagram_enabled': ig_key in request.POST,
                },
            )

        success_message = f"Notification settings for '{selected_project.name}' saved! Channel alerts will strictly dispatch for your selected options."

    # Ensure matrix exists
    settings_matrix = selected_project.get_or_create_severity_settings()

    context = {
        'projects': proj_qs,
        'selected_project': selected_project,
        'settings_matrix': settings_matrix,
        'success_message': success_message,
    }
    return render(request, 'dashboard/settings.html', context)
