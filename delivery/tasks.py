"""Celery background tasks for reliable notification delivery and DLQ management."""
import logging
from celery import shared_task
from django.conf import settings
from django.utils import timezone

from channels_config.services import (
    EmailService,
    TelegramService,
    WhatsAppService,
    InstagramService,
)
from delivery.models import (
    DeliveryAttempt,
    DeliveryStatus,
    DeadLetterEntry,
)

logger = logging.getLogger(__name__)


def resolve_channels_for_notification(notification) -> list[str]:
    """
    Resolve which channels should receive this notification based on:
      0. Exception-only filter check: if project.notify_exceptions_only is enabled,
         channel alerts are only sent if an actual exception/traceback/error_type is present.
      1. Custom Routing Rules (priority ordered)
      2. Severity Channel Matrix
      3. Default fallback (only actual exceptions/errors notify by default)
    """
    from notifications.models import RoutingRule, SeverityChannelSetting, Severity

    # 0. Exception-only filter check
    if getattr(notification.project, 'notify_exceptions_only', False):
        has_exception = bool(
            notification.error_type
            or notification.traceback
            or (notification.context and ('exception' in notification.context or 'traceback' in notification.context))
        )
        if not has_exception:
            logger.info(
                f"Notification {notification.id} skipped for channels: project "
                f"'{notification.project.name}' has notify_exceptions_only enabled and no exception was detected."
            )
            return []

    # 1. Custom Routing Rules
    rules = RoutingRule.objects.filter(project=notification.project, is_active=True)
    for rule in rules:
        if rule.matches(notification):
            return rule.get_channels()

    # 2. Project Severity Settings (Respect user configuration 100%)
    sev_setting = SeverityChannelSetting.objects.filter(
        project=notification.project,
        severity=notification.severity,
    ).first()
    if sev_setting is not None:
        return sev_setting.get_channels()

    # 3. Default fallback by severity: ONLY send alerts for actual exceptions/errors!
    # Warning, Info, and Success do NOT send channel alerts by default unless user enables them.
    if notification.severity in (Severity.CRITICAL.value, Severity.CRITICAL):
        return ['EMAIL', 'TELEGRAM']
    elif notification.severity in (Severity.ERROR.value, Severity.ERROR):
        return ['EMAIL']
    else:  # WARNING, INFO, SUCCESS
        return []


def format_notification_text(notification) -> tuple[str, str]:
    """Format subject and body for channels."""
    server_info = f' on {notification.server.name} ({notification.server.hostname})' if notification.server else ''
    service_info = f' [{notification.service_name}]' if notification.service_name else ''
    subject = f'[{notification.severity}]{service_info} {notification.title}{server_info}'

    lines = [
        f'Severity: {notification.severity}',
        f'Project: {notification.project.name} ({notification.project.environment})',
        f'Service: {notification.service_name or "N/A"}',
        f'Server: {notification.server.hostname if notification.server else "N/A"}',
        f'Timestamp: {notification.created_at.strftime("%Y-%m-%d %H:%M:%S UTC")}',
        '',
        f'Title: {notification.title}',
        '',
        'Message:',
        notification.message,
    ]

    if notification.error_type:
        lines.extend(['', f'Error Type: {notification.error_type}'])

    if notification.traceback:
        lines.extend(['', 'Traceback:', notification.traceback[:2000]])

    if notification.occurrence_count > 1:
        lines.extend(['', f'Note: This notification occurred {notification.occurrence_count} times.'])

    body = '\n'.join(lines)
    return subject, body


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def deliver_notification_task(self, notification_id: str):
    """
    Background worker task delivering a notification to resolved channels with automatic retries.
    """
    from notifications.models import Notification, NotificationStatus
    from channels_config.models import (
        EmailConfiguration,
        TelegramConfiguration,
        WhatsAppConfiguration,
        InstagramConfiguration,
    )

    try:
        notification = Notification.objects.select_related('project', 'server').get(id=notification_id)
    except Notification.DoesNotExist:
        logger.error(f'Notification {notification_id} not found for delivery')
        return

    # Skip if terminal or already processed
    if notification.status in (NotificationStatus.DELIVERED, NotificationStatus.DUPLICATE, NotificationStatus.RATE_LIMITED):
        return

    notification.status = NotificationStatus.PROCESSING
    notification.save(update_fields=['status'])

    target_channels = resolve_channels_for_notification(notification)
    if not target_channels:
        # User has not enabled notifications for this severity/event (e.g. Warning/Info or non-exception).
        # We record it in DB but do not spam channels.
        notification.status = NotificationStatus.DELIVERED
        notification.save(update_fields=['status'])
        return

    subject, body = format_notification_text(notification)

    attempt_number = self.request.retries + 1
    total_deliveries = 0
    successful_deliveries = 0
    channel_errors = []

    # 1. EMAIL
    if 'EMAIL' in target_channels:
        email_configs = EmailConfiguration.objects.filter(project=notification.project, is_active=True)
        for cfg in email_configs:
            results = EmailService.send(cfg, subject, body)
            for recipient, res in results:
                total_deliveries += 1
                att = DeliveryAttempt.objects.create(
                    notification=notification,
                    channel='EMAIL',
                    recipient=recipient,
                    status=DeliveryStatus.DELIVERED if res.success else DeliveryStatus.FAILED,
                    attempt_number=attempt_number,
                    response_code=res.status_code,
                    response_body=res.response_body[:1000],
                    error_message=res.error_message,
                    sent_at=timezone.now() if res.success else None,
                )
                if res.success:
                    successful_deliveries += 1
                else:
                    channel_errors.append(f'Email to {recipient}: {res.error_message}')

    # 2. TELEGRAM
    if 'TELEGRAM' in target_channels:
        tg_configs = TelegramConfiguration.objects.filter(project=notification.project, is_active=True)
        for cfg in tg_configs:
            # HTML message format
            tg_text = f'<b>[{notification.severity}]</b> {notification.title}\n\n' \
                      f'Project: {notification.project.name}\n' \
                      f'Service: {notification.service_name or "N/A"}\n\n' \
                      f'{notification.message[:1500]}'
            results = TelegramService.send(cfg, tg_text)
            for chat_id, res in results:
                total_deliveries += 1
                att = DeliveryAttempt.objects.create(
                    notification=notification,
                    channel='TELEGRAM',
                    recipient=str(chat_id),
                    status=DeliveryStatus.DELIVERED if res.success else DeliveryStatus.FAILED,
                    attempt_number=attempt_number,
                    response_code=res.status_code,
                    response_body=res.response_body[:1000],
                    error_message=res.error_message,
                    sent_at=timezone.now() if res.success else None,
                )
                if res.success:
                    successful_deliveries += 1
                else:
                    channel_errors.append(f'Telegram to {chat_id}: {res.error_message}')

    # 3. WHATSAPP
    if 'WHATSAPP' in target_channels:
        wa_configs = WhatsAppConfiguration.objects.filter(project=notification.project, is_active=True)
        for cfg in wa_configs:
            wa_text = f'[{notification.severity}] {notification.title}\n{notification.message[:1000]}'
            results = WhatsAppService.send(cfg, wa_text)
            for phone, res in results:
                total_deliveries += 1
                att = DeliveryAttempt.objects.create(
                    notification=notification,
                    channel='WHATSAPP',
                    recipient=phone,
                    status=DeliveryStatus.DELIVERED if res.success else DeliveryStatus.FAILED,
                    attempt_number=attempt_number,
                    response_code=res.status_code,
                    response_body=res.response_body[:1000],
                    error_message=res.error_message,
                    sent_at=timezone.now() if res.success else None,
                )
                if res.success:
                    successful_deliveries += 1
                else:
                    channel_errors.append(f'WhatsApp to {phone}: {res.error_message}')

    # 4. INSTAGRAM
    if 'INSTAGRAM' in target_channels:
        ig_configs = InstagramConfiguration.objects.filter(project=notification.project, is_active=True)
        for cfg in ig_configs:
            ig_text = f'[{notification.severity}] {notification.title}\n{notification.message[:500]}'
            results = InstagramService.send(cfg, ig_text)
            for ig_id, res in results:
                total_deliveries += 1
                att = DeliveryAttempt.objects.create(
                    notification=notification,
                    channel='INSTAGRAM',
                    recipient=ig_id,
                    status=DeliveryStatus.DELIVERED if res.success else DeliveryStatus.FAILED,
                    attempt_number=attempt_number,
                    response_code=res.status_code,
                    response_body=res.response_body[:1000],
                    error_message=res.error_message,
                    sent_at=timezone.now() if res.success else None,
                )
                if res.success:
                    successful_deliveries += 1
                else:
                    channel_errors.append(f'Instagram to {ig_id}: {res.error_message}')

    # Handle delivery status & retry logic
    max_retries = getattr(settings, 'NOTIFICATION_MAX_RETRIES', 3)
    if total_deliveries == 0:
        # No channels configured or active
        notification.status = NotificationStatus.DELIVERED
        notification.save(update_fields=['status'])
        return

    if successful_deliveries == total_deliveries:
        notification.status = NotificationStatus.DELIVERED
        notification.save(update_fields=['status'])
    elif successful_deliveries > 0:
        notification.status = NotificationStatus.PARTIALLY_DELIVERED
        notification.save(update_fields=['status'])
    else:
        # Complete failure
        if self.request.retries < max_retries:
            notification.status = NotificationStatus.PENDING
            notification.save(update_fields=['status'])
            backoff_base = getattr(settings, 'NOTIFICATION_RETRY_BACKOFF', 60)
            countdown = backoff_base * (2 ** self.request.retries)
            logger.warning(f'Retrying delivery for notification {notification.id} in {countdown}s')
            raise self.retry(countdown=countdown)
        else:
            # Retries exhausted -> Dead Letter Queue
            notification.status = NotificationStatus.FAILED
            notification.save(update_fields=['status'])
            for err in channel_errors:
                DeadLetterEntry.objects.create(
                    notification=notification,
                    channel='MIXED',
                    recipient='All recipients',
                    last_error=err,
                    total_attempts=attempt_number,
                    payload={
                        'title': notification.title,
                        'message': notification.message,
                        'severity': notification.severity,
                        'service_name': notification.service_name,
                    },
                )
            logger.error(f'Notification {notification.id} moved to Dead Letter Queue after {attempt_number} attempts')


@shared_task
def reprocess_dead_letter_task(dlq_id: str):
    """Reprocess a Dead Letter Entry."""
    try:
        dlq_entry = DeadLetterEntry.objects.select_related('notification').get(id=dlq_id)
        if dlq_entry.is_reprocessed:
            return {'status': 'already_reprocessed'}

        deliver_notification_task.delay(str(dlq_entry.notification_id))
        dlq_entry.mark_reprocessed()
        return {'status': 'reprocessed', 'notification_id': str(dlq_entry.notification_id)}
    except DeadLetterEntry.DoesNotExist:
        return {'error': 'not_found'}
