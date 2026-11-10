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
    """Render the main dashboard overview page with project, server, and severity filters."""
    user = request.user
    now = timezone.now()

    # Query parameters for filtering
    project_filter = request.GET.get('project', '').strip()
    server_filter = request.GET.get('server', '').strip()
    severity_filter = request.GET.get('severity', '').strip().upper()
    search_query = request.GET.get('q', '').strip()
    view_tab = request.GET.get('tab', 'logs').strip()  # 'logs', 'projects', 'servers'

    notif_qs = Notification.objects.all()
    delivery_qs = DeliveryAttempt.objects.all()
    proj_qs = Project.objects.all()
    server_qs = Server.objects.all()

    if user.is_authenticated and not (user.is_staff or user.is_superuser):
        notif_qs = notif_qs.filter(project__owner=user)
        delivery_qs = delivery_qs.filter(notification__project__owner=user)
        proj_qs = proj_qs.filter(owner=user)
        server_qs = server_qs.filter(project__owner=user)

    # Global counts before table filters
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

    # Display logs as per project (aggregations)
    logs_by_project = list(
        notif_qs.values('project__id', 'project__name', 'project__slug', 'project__environment', 'project__log_retention_days')
        .annotate(
            total_count=Count('id'),
            error_count=Count('id', filter=Q(severity__in=[Severity.ERROR.value, Severity.CRITICAL.value])),
            critical_count=Count('id', filter=Q(severity=Severity.CRITICAL.value)),
            unresolved_count=Count('id', filter=Q(is_resolved=False, severity__in=[Severity.ERROR.value, Severity.CRITICAL.value])),
        )
        .order_by('-total_count')
    )

    # Display logs as per server (aggregations)
    logs_by_server = list(
        notif_qs.filter(server__isnull=False)
        .values('server__id', 'server__name', 'server__hostname', 'server__environment', 'server__project__name', 'server__project__id')
        .annotate(
            total_count=Count('id'),
            error_count=Count('id', filter=Q(severity__in=[Severity.ERROR.value, Severity.CRITICAL.value])),
            critical_count=Count('id', filter=Q(severity=Severity.CRITICAL.value)),
        )
        .order_by('-total_count')
    )

    # Top 5 errors for widgets
    errors_by_project = logs_by_project[:5]
    errors_by_server = logs_by_server[:5]

    # Apply filters to the recent activity logs feed
    active_filters = {}
    selected_project = None
    selected_server = None

    if project_filter:
        p_obj = None
        try:
            import uuid as _uuid
            _uuid.UUID(project_filter)
            p_obj = proj_qs.filter(id=project_filter).first()
        except (ValueError, AttributeError):
            pass
        if not p_obj:
            p_obj = proj_qs.filter(slug=project_filter).first() or proj_qs.filter(name__iexact=project_filter).first()

        if p_obj:
            notif_qs = notif_qs.filter(project=p_obj)
            server_qs = server_qs.filter(project=p_obj)
            selected_project = p_obj
            active_filters['project'] = p_obj.name

    if server_filter:
        s_obj = None
        try:
            import uuid as _uuid
            _uuid.UUID(server_filter)
            s_obj = Server.objects.filter(id=server_filter).first()
        except (ValueError, AttributeError):
            pass
        if not s_obj:
            s_obj = Server.objects.filter(hostname=server_filter).first() or Server.objects.filter(name__iexact=server_filter).first()

        if s_obj:
            notif_qs = notif_qs.filter(server=s_obj)
            selected_server = s_obj
            active_filters['server'] = s_obj.hostname or s_obj.name

    if severity_filter and severity_filter in [s.value for s in Severity]:
        notif_qs = notif_qs.filter(severity=severity_filter)
        active_filters['severity'] = severity_filter

    if search_query:
        notif_qs = notif_qs.filter(
            Q(title__icontains=search_query) |
            Q(message__icontains=search_query) |
            Q(service_name__icontains=search_query) |
            Q(error_type__icontains=search_query)
        )
        active_filters['q'] = search_query

    filtered_logs_count = notif_qs.count()
    recent_activity = notif_qs.select_related('project', 'server').order_by('-created_at')[:50]

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
        'logs_by_project': logs_by_project,
        'logs_by_server': logs_by_server,
        'recent_activity': recent_activity,
        'filtered_logs_count': filtered_logs_count,
        'projects': proj_qs,
        'servers': server_qs,
        'severities': [s.value for s in Severity],
        'selected_project': selected_project,
        'selected_server': selected_server,
        'selected_severity': severity_filter,
        'search_query': search_query,
        'active_filters': active_filters,
        'view_tab': view_tab,
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
        action = request.POST.get('action', 'save_settings')

        if action == 'prune_now':
            count = selected_project.prune_expired_logs(keep_unresolved=True)
            success_message = f"Log cleanup complete! Pruned {count} logs older than {selected_project.log_retention_days} days for '{selected_project.name}'."
        else:
            # Update project settings
            selected_project.notify_exceptions_only = 'notify_exceptions_only' in request.POST

            retention_raw = request.POST.get('log_retention_days')
            if retention_raw is not None:
                try:
                    selected_project.log_retention_days = max(0, int(retention_raw))
                except (ValueError, TypeError):
                    pass

            selected_project.save(update_fields=['notify_exceptions_only', 'log_retention_days', 'updated_at'])

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

            success_message = (
                f"Notification settings for '{selected_project.name}' saved! "
                f"Log retention is set to {selected_project.log_retention_days} days."
            )

    # Ensure matrix exists
    settings_matrix = selected_project.get_or_create_severity_settings()

    context = {
        'projects': proj_qs,
        'selected_project': selected_project,
        'settings_matrix': settings_matrix,
        'success_message': success_message,
    }
    return render(request, 'dashboard/settings.html', context)
