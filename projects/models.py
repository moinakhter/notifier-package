"""Models for project, API keys, and server management."""
import secrets
import uuid
import hashlib
from django.db import models
from django.conf import settings
from django.utils import timezone
from django.utils.text import slugify


class Environment(models.TextChoices):
    DEVELOPMENT = 'development', 'Development'
    STAGING = 'staging', 'Staging'
    PRODUCTION = 'production', 'Production'


class Project(models.Model):
    """A project sending notifications."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True, blank=True)
    description = models.TextField(blank=True, default='')
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='projects',
        null=True,
        blank=True,
    )
    environment = models.CharField(
        max_length=20,
        choices=Environment.choices,
        default=Environment.DEVELOPMENT,
    )
    is_active = models.BooleanField(default=True)
    notify_exceptions_only = models.BooleanField(
        default=False,
        help_text='Only dispatch channel notifications when an actual exception or traceback is captured',
    )
    rate_limit = models.IntegerField(
        default=100,
        help_text='Maximum notifications per minute',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name} [{self.environment}]'

    def get_or_create_severity_settings(self):
        """
        Ensure default severity channel settings exist for all 5 severities:
          - CRITICAL: Email + Telegram enabled
          - ERROR: Email enabled
          - WARNING: All disabled (no channel alerts by default)
          - INFO: All disabled (no channel alerts by default)
          - SUCCESS: All disabled (no channel alerts by default)
        """
        from notifications.models import Severity, SeverityChannelSetting
        matrix = []
        default_configs = {
            Severity.CRITICAL.value: {'email_enabled': True, 'telegram_enabled': True, 'whatsapp_enabled': False, 'instagram_enabled': False},
            Severity.ERROR.value: {'email_enabled': True, 'telegram_enabled': False, 'whatsapp_enabled': False, 'instagram_enabled': False},
            Severity.WARNING.value: {'email_enabled': False, 'telegram_enabled': False, 'whatsapp_enabled': False, 'instagram_enabled': False},
            Severity.INFO.value: {'email_enabled': False, 'telegram_enabled': False, 'whatsapp_enabled': False, 'instagram_enabled': False},
            Severity.SUCCESS.value: {'email_enabled': False, 'telegram_enabled': False, 'whatsapp_enabled': False, 'instagram_enabled': False},
        }
        for sev_choice, defaults in default_configs.items():
            setting, _ = SeverityChannelSetting.objects.get_or_create(
                project=self,
                severity=sev_choice,
                defaults=defaults,
            )
            matrix.append(setting)
        return matrix

    @classmethod
    def get_default_project(cls) -> 'Project':
        """Get or create the default zero-config project."""
        project, _ = cls.objects.get_or_create(
            slug='default-project',
            defaults={
                'name': 'Default Project',
                'environment': Environment.DEVELOPMENT,
                'description': 'Zero-configuration default project for unauthenticated ingestion',
                'rate_limit': 1000,
            },
        )
        return project

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.name) or 'project'
            unique_slug = base_slug
            counter = 1
            while Project.objects.filter(slug=unique_slug).exclude(pk=self.pk).exists():
                unique_slug = f'{base_slug}-{counter}'
                counter += 1
            self.slug = unique_slug
        super().save(*args, **kwargs)


class APIKey(models.Model):
    """API key for authenticating project notifications."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name='api_keys',
    )
    name = models.CharField(max_length=255, help_text='Descriptive name for this key')
    prefix = models.CharField(max_length=12, unique=True, editable=False)
    hashed_key = models.CharField(max_length=128, editable=False)
    is_active = models.BooleanField(default=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'API Key'
        verbose_name_plural = 'API Keys'

    def __str__(self):
        return f'{self.name} ({self.prefix}... - {self.project.name})'

    @classmethod
    def generate_raw_key(cls) -> tuple[str, str, str]:
        """Generate prefix, raw_key, hashed_key."""
        token = secrets.token_urlsafe(36)
        prefix = f'ntf_{token[:8]}'
        full_key = f'{prefix}_{token[8:]}'
        hashed = cls.hash_key(full_key)
        return prefix, full_key, hashed

    @staticmethod
    def hash_key(key: str) -> str:
        """Hash an API key securely with SHA-256."""
        return hashlib.sha256(key.encode('utf-8')).hexdigest()

    def revoke(self):
        """Revoke this API key."""
        self.is_active = False
        self.revoked_at = timezone.now()
        self.save(update_fields=['is_active', 'revoked_at'])

    def rotate(self, new_name: str | None = None) -> tuple['APIKey', str]:
        """Rotate this key by revoking current key and creating a new one."""
        self.revoke()
        prefix, full_key, hashed = APIKey.generate_raw_key()
        new_key = APIKey.objects.create(
            project=self.project,
            name=new_name or f'{self.name} (Rotated)',
            prefix=prefix,
            hashed_key=hashed,
            expires_at=self.expires_at,
        )
        return new_key, full_key

    @property
    def is_expired(self) -> bool:
        """Check if the key has expired."""
        if self.expires_at is None:
            return False
        return timezone.now() >= self.expires_at


class Server(models.Model):
    """A registered server under a project."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name='servers',
    )
    name = models.CharField(max_length=255)
    hostname = models.CharField(max_length=255)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    environment = models.CharField(
        max_length=20,
        choices=Environment.choices,
        default=Environment.DEVELOPMENT,
    )
    is_active = models.BooleanField(default=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = ['project', 'hostname']

    def __str__(self):
        return f'{self.name} ({self.hostname})'

    def touch(self):
        """Update last seen timestamp."""
        self.last_seen_at = timezone.now()
        self.save(update_fields=['last_seen_at'])
