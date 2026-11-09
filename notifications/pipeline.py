"""Notification ingestion pipeline: rate limiting, deduplication, grouping, and queuing."""
import hashlib
import time
from datetime import timedelta
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from .models import (
    Notification,
    NotificationStatus,
    NotificationTemplate,
    Severity,
)


class IngestionPipeline:
    """Orchestrates intake, rate limiting, deduping, grouping, and queueing."""

    @classmethod
    def process_notification(
        cls,
        project,
        title: str,
        message: str = '',
        severity: str = Severity.ERROR,
        server=None,
        service_name: str = '',
        error_type: str = '',
        traceback: str = '',
        context: dict | None = None,
        idempotency_key: str | None = None,
        template_name: str | None = None,
    ) -> tuple[Notification, bool, str]:
        """
        Processes incoming notification.
        Returns (notification_instance, is_queued_for_delivery, action_summary).
        """
        context = context or {}

        # 1. Template Rendering
        if template_name:
            template = NotificationTemplate.objects.filter(
                project=project,
                name=template_name,
                is_active=True,
            ).first()
            if template:
                rendered_title, rendered_message = template.render({
                    **context,
                    'service': service_name,
                    'server': server.name if server else 'Unknown Server',
                    'error_type': error_type,
                    'severity': severity,
                })
                title = rendered_title or title
                message = rendered_message or message
                severity = template.severity

        # 2. Idempotency Check
        if idempotency_key:
            existing = Notification.objects.filter(
                project=project,
                idempotency_key=idempotency_key,
            ).first()
            if existing:
                return existing, False, 'idempotent_duplicate'

        # 3. Rate Limiting Check (Redis / Cache sliding counter)
        rate_limit = project.rate_limit or getattr(settings, 'NOTIFICATION_RATE_LIMIT', 100)
        is_rate_limited = cls._check_rate_limit(project.id, rate_limit)

        # Compute content hash
        temp_hash = hashlib.sha256(
            f'{project.id}:{title.strip().lower()}:{error_type}:{service_name}'.encode('utf-8')
        ).hexdigest()
        group_key = f'{project.id}:{service_name}:{error_type or title.strip().lower()}'

        if is_rate_limited:
            notif = Notification.objects.create(
                project=project,
                server=server,
                title=title,
                message=message,
                severity=severity,
                service_name=service_name,
                error_type=error_type,
                traceback=traceback,
                context=context,
                status=NotificationStatus.RATE_LIMITED,
                idempotency_key=idempotency_key,
                content_hash=temp_hash,
                group_key=group_key,
            )
            return notif, False, 'rate_limited'

        # 4. Duplicate Detection (within dedup window, e.g. 5 minutes)
        dedup_window = getattr(settings, 'NOTIFICATION_DEDUP_WINDOW', 300)
        since_dedup = timezone.now() - timedelta(seconds=dedup_window)

        recent_duplicate = Notification.objects.filter(
            project=project,
            content_hash=temp_hash,
            created_at__gte=since_dedup,
        ).exclude(status__in=[NotificationStatus.DUPLICATE, NotificationStatus.RATE_LIMITED]).first()

        if recent_duplicate:
            # Mark as duplicate and reference parent
            notif = Notification.objects.create(
                project=project,
                server=server,
                title=title,
                message=message,
                severity=severity,
                service_name=service_name,
                error_type=error_type,
                traceback=traceback,
                context=context,
                status=NotificationStatus.DUPLICATE,
                idempotency_key=idempotency_key,
                content_hash=temp_hash,
                group_key=group_key,
                parent_notification=recent_duplicate,
            )
            # Increment occurrence count on root duplicate
            Notification.objects.filter(pk=recent_duplicate.pk).update(
                occurrence_count=recent_duplicate.occurrence_count + 1
            )
            return notif, False, 'duplicate_detected'

        # 5. Notification Grouping (within grouping window, e.g. 60s)
        group_window = getattr(settings, 'NOTIFICATION_GROUP_WINDOW', 60)
        since_group = timezone.now() - timedelta(seconds=group_window)

        parent_group = Notification.objects.filter(
            project=project,
            group_key=group_key,
            created_at__gte=since_group,
            parent_notification__isnull=True,
        ).exclude(status__in=[NotificationStatus.DUPLICATE, NotificationStatus.RATE_LIMITED, NotificationStatus.GROUPED]).first()

        if parent_group:
            notif = Notification.objects.create(
                project=project,
                server=server,
                title=title,
                message=message,
                severity=severity,
                service_name=service_name,
                error_type=error_type,
                traceback=traceback,
                context=context,
                status=NotificationStatus.GROUPED,
                idempotency_key=idempotency_key,
                content_hash=temp_hash,
                group_key=group_key,
                parent_notification=parent_group,
            )
            Notification.objects.filter(pk=parent_group.pk).update(
                occurrence_count=parent_group.occurrence_count + 1
            )
            return notif, False, 'notification_grouped'

        # 6. Standard Notification: Create and Queue for Background Delivery
        notif = Notification.objects.create(
            project=project,
            server=server,
            title=title,
            message=message,
            severity=severity,
            service_name=service_name,
            error_type=error_type,
            traceback=traceback,
            context=context,
            status=NotificationStatus.PENDING,
            idempotency_key=idempotency_key,
            content_hash=temp_hash,
            group_key=group_key,
        )

        # Trigger Celery Task asynchronously (non-blocking)
        cls._dispatch_async_delivery(notif)
        return notif, True, 'queued_for_delivery'

    @classmethod
    def _check_rate_limit(cls, project_id, max_per_minute: int) -> bool:
        """
        Sliding 1-minute window rate limit using cache.
        Returns True if rate limit is exceeded.
        """
        minute_bucket = int(time.time() // 60)
        cache_key = f'ratelimit:proj:{project_id}:{minute_bucket}'
        try:
            current_count = cache.get(cache_key, 0)
            if current_count >= max_per_minute:
                return True
            # Increment and set expire of 70s
            new_count = cache.incr(cache_key) if current_count > 0 else 1
            if current_count == 0:
                cache.set(cache_key, 1, timeout=70)
            return new_count > max_per_minute
        except Exception:
            # Fail open if cache is temporarily unreachable
            return False

    @classmethod
    def _dispatch_async_delivery(cls, notification: Notification):
        """Asynchronously dispatch to Celery worker."""
        try:
            from delivery.tasks import deliver_notification_task
            deliver_notification_task.delay(str(notification.id))
        except Exception as e:
            # If celery is running in eager mode or fails to connect, fallback gracefully
            pass
