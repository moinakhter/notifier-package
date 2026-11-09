"""Models for notifications, templates, routing rules, and severity settings."""
import hashlib
import re
import uuid
from django.db import models
from django.conf import settings
from django.utils import timezone


class Severity(models.TextChoices):
    CRITICAL = 'CRITICAL', 'Critical'
    ERROR = 'ERROR', 'Error'
    WARNING = 'WARNING', 'Warning'
    INFO = 'INFO', 'Info'
    SUCCESS = 'SUCCESS', 'Success'


class NotificationStatus(models.TextChoices):
    PENDING = 'PENDING', 'Pending'
    PROCESSING = 'PROCESSING', 'Processing'
    DELIVERED = 'DELIVERED', 'Delivered'
    PARTIALLY_DELIVERED = 'PARTIALLY_DELIVERED', 'Partially Delivered'
    FAILED = 'FAILED', 'Failed'
    GROUPED = 'GROUPED', 'Grouped'
    DUPLICATE = 'DUPLICATE', 'Duplicate'
    RATE_LIMITED = 'RATE_LIMITED', 'Rate Limited'


class Notification(models.Model):
    """Core notification event record."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(
        'projects.Project',
        on_delete=models.CASCADE,
        related_name='notifications',
    )
    server = models.ForeignKey(
        'projects.Server',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='notifications',
    )

    # Content
    title = models.CharField(max_length=500)
    message = models.TextField()
    severity = models.CharField(
        max_length=20,
        choices=Severity.choices,
        default=Severity.ERROR,
        db_index=True,
    )
    service_name = models.CharField(
        max_length=255,
        blank=True,
        default='',
        db_index=True,
        help_text='Name of service or microservice generating the notification',
    )

    # Error details
    error_type = models.CharField(max_length=255, blank=True, default='', db_index=True)
    traceback = models.TextField(blank=True, default='', help_text='Full error traceback')
    context = models.JSONField(
        default=dict,
        blank=True,
        help_text='Arbitrary structured context (request headers, query params, etc.)',
    )

    # Lifecycle & Deduplication
    status = models.CharField(
        max_length=20,
        choices=NotificationStatus.choices,
        default=NotificationStatus.PENDING,
        db_index=True,
    )
    idempotency_key = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        db_index=True,
        help_text='Client idempotency key to prevent double posting',
    )
    content_hash = models.CharField(
        max_length=64,
        db_index=True,
        help_text='SHA256 hash of notification fingerprint for duplicate detection',
    )
    group_key = models.CharField(
        max_length=255,
        blank=True,
        default='',
        db_index=True,
        help_text='Key used to group related events',
    )
    parent_notification = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='grouped_notifications',
        help_text='Parent notification if this was rolled into a group',
    )
    occurrence_count = models.IntegerField(
        default=1,
        help_text='Count of occurrences for grouped events',
    )

    # Resolution & Triage
    is_acknowledged = models.BooleanField(default=False, db_index=True)
    acknowledged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='acknowledged_notifications',
    )
    acknowledged_at = models.DateTimeField(null=True, blank=True)

    is_resolved = models.BooleanField(default=False, db_index=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='resolved_notifications',
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_note = models.TextField(blank=True, default='')

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['project', 'severity', '-created_at']),
            models.Index(fields=['project', 'status', '-created_at']),
            models.Index(fields=['project', 'service_name', '-created_at']),
            models.Index(fields=['content_hash', '-created_at']),
            models.Index(fields=['idempotency_key', 'project']),
        ]

    def __str__(self):
        return f'[{self.severity}] {self.title[:60]} ({self.project.name})'

    def compute_content_hash(self) -> str:
        """Compute SHA-256 fingerprint for duplicate detection."""
        seed = f'{self.project_id}:{self.title.strip().lower()}:{self.error_type}:{self.service_name}'
        return hashlib.sha256(seed.encode('utf-8')).hexdigest()

    def compute_group_key(self) -> str:
        """Compute group key for collapsing identical error types in the same service."""
        return f'{self.project_id}:{self.service_name}:{self.error_type or self.title.strip().lower()}'

    def save(self, *args, **kwargs):
        if not self.content_hash:
            self.content_hash = self.compute_content_hash()
        if not self.group_key:
            self.group_key = self.compute_group_key()
        super().save(*args, **kwargs)

    def acknowledge(self, user=None):
        self.is_acknowledged = True
        self.acknowledged_by = user
        self.acknowledged_at = timezone.now()
        self.save(update_fields=['is_acknowledged', 'acknowledged_by', 'acknowledged_at', 'updated_at'])

    def resolve(self, user=None, note: str = ''):
        self.is_resolved = True
        self.resolved_by = user
        self.resolved_at = timezone.now()
        self.resolution_note = note
        self.save(update_fields=['is_resolved', 'resolved_by', 'resolved_at', 'resolution_note', 'updated_at'])


class NotificationTemplate(models.Model):
    """Reusable template for standardizing notification title and body formatting."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(
        'projects.Project',
        on_delete=models.CASCADE,
        related_name='notification_templates',
    )
    name = models.CharField(max_length=255)
    severity = models.CharField(
        max_length=20,
        choices=Severity.choices,
        default=Severity.ERROR,
    )
    title_template = models.CharField(
        max_length=500,
        help_text='Title template supporting placeholders like {service}, {server}, {error_type}',
    )
    message_template = models.TextField(
        help_text='Body template supporting placeholders like {message}, {traceback}, {context}',
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = ['project', 'name']

    def __str__(self):
        return f'{self.name} [{self.severity}] ({self.project.name})'

    def render(self, context_dict: dict) -> tuple[str, str]:
        """Safely render title and message templates using provided variables."""
        class SafeDict(dict):
            def __missing__(self, key):
                return f'{{{key}}}'

        safe_ctx = SafeDict(context_dict)
        title = self.title_template.format_map(safe_ctx)
        message = self.message_template.format_map(safe_ctx)
        return title, message


class RoutingRule(models.Model):
    """Custom routing rules to direct notifications to specific channels."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(
        'projects.Project',
        on_delete=models.CASCADE,
        related_name='routing_rules',
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default='')

    # Match filters
    severity = models.CharField(
        max_length=20,
        choices=Severity.choices,
        null=True,
        blank=True,
        help_text='Filter by severity. Leave blank to match any severity.',
    )
    service_name_pattern = models.CharField(
        max_length=255,
        blank=True,
        default='',
        help_text='Regex pattern to match service_name (e.g. ^auth-.*). Empty matches all.',
    )
    title_pattern = models.CharField(
        max_length=255,
        blank=True,
        default='',
        help_text='Regex pattern to match title. Empty matches all.',
    )

    # Destination channels
    email_enabled = models.BooleanField(default=False)
    telegram_enabled = models.BooleanField(default=False)
    whatsapp_enabled = models.BooleanField(default=False)
    instagram_enabled = models.BooleanField(default=False)

    priority = models.IntegerField(default=10, help_text='Higher priority rules evaluated first')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-priority', '-created_at']

    def __str__(self):
        return f'{self.name} (Priority {self.priority}) - {self.project.name}'

    def matches(self, notification: Notification) -> bool:
        """Check if notification satisfies this rule's conditions."""
        if not self.is_active:
            return False

        if self.severity and notification.severity != self.severity:
            return False

        if self.service_name_pattern:
            try:
                if not re.search(self.service_name_pattern, notification.service_name or '', re.IGNORECASE):
                    return False
            except re.error:
                return False

        if self.title_pattern:
            try:
                if not re.search(self.title_pattern, notification.title or '', re.IGNORECASE):
                    return False
            except re.error:
                return False

        return True

    def get_channels(self) -> list[str]:
        channels = []
        if self.email_enabled:
            channels.append('EMAIL')
        if self.telegram_enabled:
            channels.append('TELEGRAM')
        if self.whatsapp_enabled:
            channels.append('WHATSAPP')
        if self.instagram_enabled:
            channels.append('INSTAGRAM')
        return channels


class SeverityChannelSetting(models.Model):
    """
    Project-wide setting enabling or disabling delivery channels per severity level.
    e.g. CRITICAL -> [EMAIL, TELEGRAM, WHATSAPP]
         INFO     -> [EMAIL]
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(
        'projects.Project',
        on_delete=models.CASCADE,
        related_name='severity_channel_settings',
    )
    severity = models.CharField(max_length=20, choices=Severity.choices)
    email_enabled = models.BooleanField(default=True)
    telegram_enabled = models.BooleanField(default=True)
    whatsapp_enabled = models.BooleanField(default=False)
    instagram_enabled = models.BooleanField(default=False)

    class Meta:
        unique_together = ['project', 'severity']
        ordering = ['project', 'severity']

    def __str__(self):
        return f'{self.project.name} - {self.severity}'

    def get_channels(self) -> list[str]:
        channels = []
        if self.email_enabled:
            channels.append('EMAIL')
        if self.telegram_enabled:
            channels.append('TELEGRAM')
        if self.whatsapp_enabled:
            channels.append('WHATSAPP')
        if self.instagram_enabled:
            channels.append('INSTAGRAM')
        return channels
