"""Management command to populate rich seed data for development and demonstration."""
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone

from projects.models import Project, Server, APIKey, Environment
from channels_config.models import (
    EmailConfiguration,
    TelegramConfiguration,
    WhatsAppConfiguration,
    InstagramConfiguration,
)
from notifications.models import (
    Notification,
    Severity,
    NotificationStatus,
    NotificationTemplate,
    RoutingRule,
    SeverityChannelSetting,
)
from delivery.models import DeliveryAttempt, DeadLetterEntry, DeliveryStatus

User = get_user_model()


class Command(BaseCommand):
    help = 'Seeds database with realistic projects, servers, API keys, channels, and notifications'

    def handle(self, *args, **options):
        self.stdout.write('Seeding database with demo data...')

        # 1. Superuser
        admin_user, _ = User.objects.get_or_create(
            username='admin',
            defaults={
                'email': 'admin@notifier.local',
                'is_staff': True,
                'is_superuser': True,
            },
        )
        admin_user.set_password('admin123')
        admin_user.save()

        # 2. Projects
        prod_project, _ = Project.objects.get_or_create(
            name='E-Commerce Platform',
            owner=admin_user,
            defaults={
                'environment': Environment.PRODUCTION,
                'description': 'Main customer storefront and payment pipelines',
                'rate_limit': 150,
            },
        )

        staging_project, _ = Project.objects.get_or_create(
            name='Analytics & BI Engine',
            owner=admin_user,
            defaults={
                'environment': Environment.STAGING,
                'description': 'Big data reporting pipelines',
                'rate_limit': 60,
            },
        )

        dev_project, _ = Project.objects.get_or_create(
            name='Inventory Microservice',
            owner=admin_user,
            defaults={
                'environment': Environment.DEVELOPMENT,
                'description': 'Warehouse sync and stock levels',
                'rate_limit': 30,
            },
        )

        # 3. Servers
        gw_server, _ = Server.objects.get_or_create(
            project=prod_project,
            hostname='gateway-prod-01.us-east-1',
            defaults={
                'name': 'API Gateway 01',
                'ip_address': '10.0.1.15',
                'environment': Environment.PRODUCTION,
            },
        )

        worker_server, _ = Server.objects.get_or_create(
            project=prod_project,
            hostname='worker-prod-03.us-east-1',
            defaults={
                'name': 'Celery Worker 03',
                'ip_address': '10.0.2.88',
                'environment': Environment.PRODUCTION,
            },
        )

        db_server, _ = Server.objects.get_or_create(
            project=prod_project,
            hostname='pg-primary.prod.internal',
            defaults={
                'name': 'Postgres Primary',
                'ip_address': '10.0.3.10',
                'environment': Environment.PRODUCTION,
            },
        )

        # 4. API Keys
        prefix, raw_key, hashed = APIKey.generate_raw_key()
        api_key, created = APIKey.objects.get_or_create(
            project=prod_project,
            name='Storefront Backend Key',
            defaults={
                'prefix': prefix,
                'hashed_key': hashed,
            },
        )

        # 5. Channel Configurations
        email_cfg, _ = EmailConfiguration.objects.get_or_create(
            project=prod_project,
            name='Ops Alerts SMTP',
            defaults={
                'smtp_host': 'smtp.sendgrid.net',
                'smtp_port': 587,
                'from_email': 'alerts@mycompany.com',
                'recipients': ['oncall@mycompany.com', 'devops@mycompany.com'],
                'is_active': True,
                'is_verified': True,
            },
        )

        tg_cfg, _ = TelegramConfiguration.objects.get_or_create(
            project=prod_project,
            name='Core Incident Bot',
            defaults={
                'bot_token': '123456789:ABCdefGHIjklMNOpqrSTUvwxYZ',
                'chat_ids': ['-100987654321', '12345678'],
                'parse_mode': 'HTML',
                'is_active': True,
                'is_verified': True,
            },
        )

        wa_cfg, _ = WhatsAppConfiguration.objects.get_or_create(
            project=prod_project,
            name='On-Call Pager WhatsApp',
            defaults={
                'phone_number_id': '10987654321',
                'access_token': 'EAAK...token',
                'recipient_numbers': ['+15551234567'],
                'is_active': True,
                'is_verified': True,
            },
        )

        ig_cfg, _ = InstagramConfiguration.objects.get_or_create(
            project=prod_project,
            name='Public Relations Escalations',
            defaults={
                'page_id': '100200300',
                'access_token': 'IG...token',
                'instagram_account_id': '17841400000',
                'recipient_ids': ['ig_admin_01'],
                'is_active': True,
                'is_verified': True,
            },
        )

        # 6. Templates
        NotificationTemplate.objects.get_or_create(
            project=prod_project,
            name='service_crash',
            defaults={
                'severity': Severity.CRITICAL,
                'title_template': 'CRITICAL: Service {service} crashed on {server}',
                'message_template': 'Exception: {error_type}. Stack trace available in monitoring dashboard.',
            },
        )

        NotificationTemplate.objects.get_or_create(
            project=prod_project,
            name='database_failover',
            defaults={
                'severity': Severity.WARNING,
                'title_template': 'PostgreSQL Failover triggered on {server}',
                'message_template': 'Replica promoted to primary. Connection pool reset.',
            },
        )

        # 7. Routing Rules
        RoutingRule.objects.get_or_create(
            project=prod_project,
            name='Payment Gateway Critical Routing',
            defaults={
                'severity': Severity.CRITICAL,
                'service_name_pattern': r'payment|checkout',
                'email_enabled': True,
                'telegram_enabled': True,
                'whatsapp_enabled': True,
                'instagram_enabled': False,
                'priority': 100,
            },
        )

        # 8. Notifications & Delivery History
        now = timezone.now()

        # Critical Error 1
        n1, _ = Notification.objects.get_or_create(
            project=prod_project,
            server=db_server,
            title='PostgreSQL Connection Pool Exhausted',
            defaults={
                'message': 'Max connections (200/200) reached. Incoming checkout queries are timing out.',
                'severity': Severity.CRITICAL,
                'service_name': 'checkout-api',
                'error_type': 'OperationalError',
                'traceback': 'django.db.utils.OperationalError: FATAL: remaining connection slots are reserved for non-replication superuser connections\n  at django/db/backends/base/base.py:279 in get_new_connection',
                'status': NotificationStatus.DELIVERED,
                'occurrence_count': 14,
                'is_acknowledged': True,
                'acknowledged_by': admin_user,
                'acknowledged_at': now - timedelta(minutes=45),
            },
        )

        # Critical Error 2
        n2, _ = Notification.objects.get_or_create(
            project=prod_project,
            server=gw_server,
            title='OOM Killed: Memory Spike in Order Processor',
            defaults={
                'message': 'Pod memory reached 4.1GB / 4.0GB limit. Kernel invoked oom-killer on PID 4192.',
                'severity': Severity.CRITICAL,
                'service_name': 'order-processor',
                'error_type': 'OutOfMemoryError',
                'traceback': 'Fatal Python error: OutOfMemory\nKernel log: Memory cgroup out of memory: Kill process 4192 (gunicorn worker)',
                'status': NotificationStatus.DELIVERED,
                'occurrence_count': 3,
                'is_resolved': False,
            },
        )

        # Error
        n3, _ = Notification.objects.get_or_create(
            project=prod_project,
            server=worker_server,
            title='Stripe Webhook Signature Verification Failed',
            defaults={
                'message': 'Incoming webhook header Stripe-Signature did not match webhook secret.',
                'severity': Severity.ERROR,
                'service_name': 'stripe-listener',
                'error_type': 'SignatureVerificationError',
                'status': NotificationStatus.DELIVERED,
                'occurrence_count': 1,
            },
        )

        # Warning
        n4, _ = Notification.objects.get_or_create(
            project=prod_project,
            server=gw_server,
            title='High API Gateway Latency (p99 > 850ms)',
            defaults={
                'message': 'p99 response time degraded to 920ms on route /api/v1/checkout/orders',
                'severity': Severity.WARNING,
                'service_name': 'api-gateway',
                'status': NotificationStatus.DELIVERED,
            },
        )

        # Info
        n5, _ = Notification.objects.get_or_create(
            project=prod_project,
            server=gw_server,
            title='Blue/Green Deployment Promoted v2.8.0',
            defaults={
                'message': 'Traffic shifted 100% to green container cluster. Health checks passed.',
                'severity': Severity.INFO,
                'service_name': 'deploy-orchestrator',
                'status': NotificationStatus.DELIVERED,
            },
        )

        # Success
        n6, _ = Notification.objects.get_or_create(
            project=prod_project,
            title='Nightly Database Backup Uploaded to S3',
            defaults={
                'message': 'Backup snapshot (48.2 GB) verified with SHA256 checksum in us-east-1.',
                'severity': Severity.SUCCESS,
                'service_name': 'backup-cron',
                'status': NotificationStatus.DELIVERED,
            },
        )

        # Delivery attempts
        DeliveryAttempt.objects.get_or_create(
            notification=n1,
            channel='EMAIL',
            recipient='oncall@mycompany.com',
            defaults={
                'status': DeliveryStatus.DELIVERED,
                'attempt_number': 1,
                'response_code': 250,
                'sent_at': now - timedelta(minutes=44),
            },
        )

        DeliveryAttempt.objects.get_or_create(
            notification=n1,
            channel='TELEGRAM',
            recipient='-100987654321',
            defaults={
                'status': DeliveryStatus.DELIVERED,
                'attempt_number': 1,
                'response_code': 200,
                'sent_at': now - timedelta(minutes=44),
            },
        )

        DeliveryAttempt.objects.get_or_create(
            notification=n2,
            channel='WHATSAPP',
            recipient='+15551234567',
            defaults={
                'status': DeliveryStatus.DELIVERED,
                'attempt_number': 1,
                'response_code': 200,
                'sent_at': now - timedelta(minutes=20),
            },
        )

        # Dead Letter Entry
        DeadLetterEntry.objects.get_or_create(
            notification=n3,
            channel='EMAIL',
            recipient='corrupted-mailbox@example.invalid',
            defaults={
                'last_error': 'SMTP 550 Recipient address rejected: domain does not exist',
                'total_attempts': 3,
                'payload': {'title': n3.title, 'severity': n3.severity},
            },
        )

        self.stdout.write(self.style.SUCCESS(
            f'Seeding complete!\n'
            f'  Superuser: admin / admin123\n'
            f'  Demo Project: {prod_project.name} (Production)\n'
            f'  API Key: {raw_key}\n'
            f'  Total notifications seeded: {Notification.objects.count()}'
        ))
