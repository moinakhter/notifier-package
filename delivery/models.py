"""Models for delivery attempts and dead-letter queue."""
import uuid
from django.db import models
from django.utils import timezone


class DeliveryStatus(models.TextChoices):
    PENDING = 'PENDING', 'Pending'
    SENT = 'SENT', 'Sent'
    DELIVERED = 'DELIVERED', 'Delivered'
    FAILED = 'FAILED', 'Failed'
    RETRYING = 'RETRYING', 'Retrying'
    DEAD_LETTER = 'DEAD_LETTER', 'Dead Letter'


class DeliveryAttempt(models.Model):
    """Detailed record of each delivery attempt per channel and recipient."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    notification = models.ForeignKey(
        'notifications.Notification',
        on_delete=models.CASCADE,
        related_name='delivery_attempts',
    )
    channel = models.CharField(
        max_length=20,
        choices=[
            ('EMAIL', 'Email'),
            ('TELEGRAM', 'Telegram'),
            ('WHATSAPP', 'WhatsApp'),
            ('INSTAGRAM', 'Instagram'),
        ],
    )
    recipient = models.CharField(
        max_length=255,
        help_text='Recipient address/identifier (email, chat ID, phone, etc.)',
    )
    status = models.CharField(
        max_length=20,
        choices=DeliveryStatus.choices,
        default=DeliveryStatus.PENDING,
    )
    attempt_number = models.IntegerField(default=1)
    response_code = models.IntegerField(null=True, blank=True)
    response_body = models.TextField(blank=True, default='')
    error_message = models.TextField(blank=True, default='')
    sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['notification', 'channel']),
            models.Index(fields=['status', '-created_at']),
        ]

    def __str__(self):
        return f'{self.channel} -> {self.recipient} ({self.status})'


class DeadLetterEntry(models.Model):
    """Dead-letter queue for permanently failed notifications after retries exhausted."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    notification = models.ForeignKey(
        'notifications.Notification',
        on_delete=models.CASCADE,
        related_name='dead_letter_entries',
    )
    channel = models.CharField(max_length=20)
    recipient = models.CharField(max_length=255)
    last_error = models.TextField()
    total_attempts = models.IntegerField(default=0)
    payload = models.JSONField(
        default=dict,
        help_text='Saved notification payload attempted during delivery',
    )
    is_reprocessed = models.BooleanField(default=False)
    reprocessed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Dead Letter Entry'
        verbose_name_plural = 'Dead Letter Entries'

    def __str__(self):
        return f'DLQ [{self.channel}] {self.recipient} - {self.notification_id}'

    def mark_reprocessed(self):
        self.is_reprocessed = True
        self.reprocessed_at = timezone.now()
        self.save(update_fields=['is_reprocessed', 'reprocessed_at'])
