"""Models for notification channel configurations."""
import uuid
from django.db import models
from django.utils import timezone


class ChannelType(models.TextChoices):
    EMAIL = 'EMAIL', 'Email'
    TELEGRAM = 'TELEGRAM', 'Telegram'
    WHATSAPP = 'WHATSAPP', 'WhatsApp'
    INSTAGRAM = 'INSTAGRAM', 'Instagram'


class BaseChannelConfig(models.Model):
    """Abstract base class for channel configurations."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)
    is_verified = models.BooleanField(default=False)
    last_tested_at = models.DateTimeField(null=True, blank=True)
    last_test_result = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

    def mark_tested(self, success: bool, message: str = ''):
        self.is_verified = success
        self.last_tested_at = timezone.now()
        self.last_test_result = message
        self.save(update_fields=['is_verified', 'last_tested_at', 'last_test_result', 'updated_at'])


class EmailConfiguration(BaseChannelConfig):
    """SMTP email configuration."""

    project = models.ForeignKey(
        'projects.Project',
        on_delete=models.CASCADE,
        related_name='email_configs',
    )
    smtp_host = models.CharField(max_length=255)
    smtp_port = models.IntegerField(default=587)
    smtp_username = models.CharField(max_length=255, blank=True, default='')
    smtp_password = models.CharField(max_length=255, blank=True, default='')
    use_tls = models.BooleanField(default=True)
    use_ssl = models.BooleanField(default=False)
    from_email = models.EmailField()
    from_name = models.CharField(max_length=255, default='Notifier Service')
    recipients = models.JSONField(
        default=list,
        help_text='List of recipient email addresses: ["ops@example.com", "alerts@example.com"]',
    )

    class Meta:
        verbose_name = 'Email Configuration'
        verbose_name_plural = 'Email Configurations'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name} - {self.from_email} ({self.project.name})'


class TelegramConfiguration(BaseChannelConfig):
    """Telegram Bot configuration."""

    project = models.ForeignKey(
        'projects.Project',
        on_delete=models.CASCADE,
        related_name='telegram_configs',
    )
    bot_token = models.CharField(max_length=255)
    chat_ids = models.JSONField(
        default=list,
        help_text='List of chat IDs: ["12345678", "-1001234567890"]',
    )
    parse_mode = models.CharField(
        max_length=20,
        choices=[('HTML', 'HTML'), ('Markdown', 'Markdown'), ('MarkdownV2', 'MarkdownV2')],
        default='HTML',
    )

    class Meta:
        verbose_name = 'Telegram Configuration'
        verbose_name_plural = 'Telegram Configurations'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name} ({self.project.name})'


class WhatsAppConfiguration(BaseChannelConfig):
    """WhatsApp Cloud API configuration."""

    project = models.ForeignKey(
        'projects.Project',
        on_delete=models.CASCADE,
        related_name='whatsapp_configs',
    )
    phone_number_id = models.CharField(max_length=255)
    access_token = models.CharField(max_length=500)
    business_account_id = models.CharField(max_length=255, blank=True, default='')
    api_version = models.CharField(max_length=10, default='v21.0')
    recipient_numbers = models.JSONField(
        default=list,
        help_text='List of recipient phone numbers with country code: ["+1234567890"]',
    )

    class Meta:
        verbose_name = 'WhatsApp Configuration'
        verbose_name_plural = 'WhatsApp Configurations'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name} ({self.project.name})'


class InstagramConfiguration(BaseChannelConfig):
    """Instagram Messaging API configuration."""

    project = models.ForeignKey(
        'projects.Project',
        on_delete=models.CASCADE,
        related_name='instagram_configs',
    )
    page_id = models.CharField(max_length=255)
    access_token = models.CharField(max_length=500)
    instagram_account_id = models.CharField(max_length=255)
    api_version = models.CharField(max_length=10, default='v21.0')
    recipient_ids = models.JSONField(
        default=list,
        help_text='List of recipient IG-scoped IDs: ["ig_user_123"]',
    )

    class Meta:
        verbose_name = 'Instagram Configuration'
        verbose_name_plural = 'Instagram Configurations'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name} ({self.project.name})'
