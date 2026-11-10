"""Comprehensive integration tests for all 6 features of Notifier Service."""
import json
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status

from projects.models import Project, APIKey, Server, Environment
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
from delivery.tasks import deliver_notification_task, reprocess_dead_letter_task

User = get_user_model()


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class NotifierServiceFeatureTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='developer',
            email='dev@example.com',
            password='password123',
        )
        self.client.force_authenticate(user=self.user)

        # 1. Setup sample project
        self.project = Project.objects.create(
            name='Ecommerce Platform',
            owner=self.user,
            environment=Environment.PRODUCTION,
            rate_limit=10,
        )

        # Setup API Key
        self.prefix, self.raw_key, hashed = APIKey.generate_raw_key()
        self.api_key = APIKey.objects.create(
            project=self.project,
            name='Production Backend Key',
            prefix=self.prefix,
            hashed_key=hashed,
        )

        # Setup Server
        self.server = Server.objects.create(
            project=self.project,
            name='API Gateway 01',
            hostname='gw01.prod.internal',
            environment=Environment.PRODUCTION,
        )

    # =========================================================================
    # FEATURE 2: PROJECT MANAGEMENT TESTS
    # =========================================================================
    def test_project_crud_and_environments(self):
        """Test creating multiple projects across dev, staging, prod."""
        # Create Staging project
        res = self.client.post('/api/v1/projects/projects/', {
            'name': 'Analytics Engine',
            'environment': 'staging',
            'description': 'Realtime analytics',
            'rate_limit': 50,
        })
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data['environment'], 'staging')

        # List projects
        res = self.client.get('/api/v1/projects/projects/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(res.data['count'], 2)

    def test_server_registration(self):
        """Test registering multiple servers per project."""
        res = self.client.post('/api/v1/projects/servers/', {
            'project': str(self.project.id),
            'name': 'Worker Node 02',
            'hostname': 'worker02.prod.internal',
            'environment': 'production',
        })
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(self.project.servers.count(), 2)

    def test_api_key_generation_rotation_and_revocation(self):
        """Test generating, rotating, and revoking API keys."""
        # Generate new key
        res = self.client.post('/api/v1/projects/api-keys/', {
            'project': str(self.project.id),
            'name': 'Microservice Key',
        })
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertIn('raw_key', res.data)
        new_key_id = res.data['id']

        # Rotate key
        res = self.client.post(f'/api/v1/projects/api-keys/{new_key_id}/rotate/', {
            'new_name': 'Microservice Key Rotated',
        })
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertTrue(res.data['old_key_revoked'])
        self.assertIn('raw_key', res.data)

        # Check old key is inactive
        old_key = APIKey.objects.get(id=new_key_id)
        self.assertFalse(old_key.is_active)
        self.assertIsNotNone(old_key.revoked_at)

        # Revoke key
        new_key_id_2 = res.data['new_key_id']
        res = self.client.post(f'/api/v1/projects/api-keys/{new_key_id_2}/revoke/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        key_obj = APIKey.objects.get(id=new_key_id_2)
        self.assertFalse(key_obj.is_active)

    # =========================================================================
    # FEATURE 3: NOTIFICATION MANAGEMENT TESTS
    # =========================================================================
    def test_notification_severities_and_ingestion(self):
        """Test ingesting notifications across all 5 severities."""
        severities = [
            Severity.CRITICAL,
            Severity.ERROR,
            Severity.WARNING,
            Severity.INFO,
            Severity.SUCCESS,
        ]
        unauthed_client = APIClient()
        unauthed_client.credentials(HTTP_X_API_KEY=self.raw_key)

        for sev in severities:
            res = unauthed_client.post('/api/v1/notifications/notify/', {
                'title': f'{sev} Alert Happened',
                'message': f'Detailed message for {sev}',
                'severity': sev,
                'service_name': 'checkout-api',
                'server_hostname': self.server.hostname,
                'error_type': f'Error_{sev}',
                'traceback': 'Traceback (most recent call last):\n  File "app.py", line 42',
            })
            self.assertEqual(res.status_code, status.HTTP_202_ACCEPTED)

        self.assertEqual(self.project.notifications.count(), 5)

    def test_notification_templates(self):
        """Test template creation and automatic variable substitution."""
        template = NotificationTemplate.objects.create(
            project=self.project,
            name='high_cpu_alert',
            severity=Severity.WARNING,
            title_template='High CPU on {server}: {usage}%',
            message_template='Service {service} exceeded threshold at {time}',
        )

        unauthed_client = APIClient()
        unauthed_client.credentials(HTTP_X_API_KEY=self.raw_key)

        res = unauthed_client.post('/api/v1/notifications/notify/', {
            'template_name': 'high_cpu_alert',
            'title': 'Fallback title',
            'service_name': 'billing-service',
            'server_hostname': self.server.hostname,
            'context': {'usage': 94, 'time': '12:00:00'},
        }, format='json')
        self.assertEqual(res.status_code, status.HTTP_202_ACCEPTED)

        notif = Notification.objects.get(id=res.data['notification_id'])
        self.assertIn('High CPU on API Gateway 01: 94%', notif.title)
        self.assertIn('Service billing-service exceeded threshold at 12:00:00', notif.message)

    def test_duplicate_detection(self):
        """Test duplicate detection suppresses duplicate alerts within dedup window."""
        unauthed_client = APIClient()
        unauthed_client.credentials(HTTP_X_API_KEY=self.raw_key)

        payload = {
            'title': 'Database Connection Timeout',
            'message': 'Cannot connect to primary DB pool',
            'severity': Severity.CRITICAL,
            'service_name': 'order-processor',
            'error_type': 'DatabaseTimeout',
        }

        # First request -> Queued
        res1 = unauthed_client.post('/api/v1/notifications/notify/', payload)
        self.assertEqual(res1.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(res1.data['action'], 'queued_for_delivery')

        # Second identical request -> Marked Duplicate
        res2 = unauthed_client.post('/api/v1/notifications/notify/', payload)
        self.assertEqual(res2.status_code, status.HTTP_200_OK)
        self.assertEqual(res2.data['status'], NotificationStatus.DUPLICATE)
        self.assertEqual(res2.data['action'], 'duplicate_detected')

    def test_notification_grouping(self):
        """Test grouping similar error types under one parent notification."""
        unauthed_client = APIClient()
        unauthed_client.credentials(HTTP_X_API_KEY=self.raw_key)

        # First error
        res1 = unauthed_client.post('/api/v1/notifications/notify/', {
            'title': 'Payment Gateway Failed: Card 1111',
            'message': 'Timeout from Stripe',
            'severity': Severity.ERROR,
            'service_name': 'payment-svc',
            'error_type': 'PaymentGatewayTimeout',
        })
        self.assertEqual(res1.data['action'], 'queued_for_delivery')

        # Second error with different title but same group key (error_type + service)
        res2 = unauthed_client.post('/api/v1/notifications/notify/', {
            'title': 'Payment Gateway Failed: Card 2222',
            'message': 'Timeout from Stripe on retry',
            'severity': Severity.ERROR,
            'service_name': 'payment-svc',
            'error_type': 'PaymentGatewayTimeout',
        })
        self.assertEqual(res2.data['status'], NotificationStatus.GROUPED)
        self.assertEqual(res2.data['action'], 'notification_grouped')

    def test_custom_routing_rules(self):
        """Test custom routing rules match patterns and enable channels."""
        rule = RoutingRule.objects.create(
            project=self.project,
            name='Payment Critical Routing',
            severity=Severity.CRITICAL,
            service_name_pattern=r'^payment-.*',
            email_enabled=True,
            telegram_enabled=True,
            whatsapp_enabled=True,
            instagram_enabled=False,
            priority=50,
        )

        notif = Notification.objects.create(
            project=self.project,
            title='Stripe Down',
            message='All charges failing',
            severity=Severity.CRITICAL,
            service_name='payment-core',
        )

        from delivery.tasks import resolve_channels_for_notification
        channels = resolve_channels_for_notification(notif)
        self.assertEqual(set(channels), {'EMAIL', 'TELEGRAM', 'WHATSAPP'})

    # =========================================================================
    # FEATURE 4: CHANNEL MANAGEMENT TESTS
    # =========================================================================
    def test_channel_configurations_and_test_connection(self):
        """Test configuring channels and running test connection."""
        # 1. Email Config
        email_cfg = EmailConfiguration.objects.create(
            project=self.project,
            name='Ops Mail',
            smtp_host='smtp.example.com',
            smtp_port=587,
            from_email='alerts@example.com',
            recipients=['ops@example.com', 'team@example.com'],
        )

        with patch('channels_config.services.EmailService.test_connection', return_value=(True, 'Connected successfully')):
            res = self.client.post(f'/api/v1/channels/email/{email_cfg.id}/test_connection/')
            self.assertEqual(res.status_code, status.HTTP_200_OK)
            self.assertTrue(res.data['is_verified'])

        # 2. Telegram Config
        tg_cfg = TelegramConfiguration.objects.create(
            project=self.project,
            name='Emergency TG',
            bot_token='123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11',
            chat_ids=['-1001234567890', '987654321'],
        )
        with patch('channels_config.services.TelegramService.test_connection', return_value=(True, 'Connected to @AlertBot')):
            res = self.client.post(f'/api/v1/channels/telegram/{tg_cfg.id}/test_connection/')
            self.assertEqual(res.status_code, status.HTTP_200_OK)
            self.assertTrue(res.data['is_verified'])

    # =========================================================================
    # FEATURE 5: NOTIFICATION HISTORY, TRIAGE & EXPORT
    # =========================================================================
    def test_notification_history_triage_and_export(self):
        """Test search, filters, acknowledge, resolve, and CSV/JSON export."""
        notif = Notification.objects.create(
            project=self.project,
            server=self.server,
            title='NullPointerException in AuthService',
            message='User session was null',
            severity=Severity.CRITICAL,
            service_name='auth-service',
            error_type='NullPointerException',
            traceback='Traceback line 10\nNullPointer at auth.py:55',
        )

        # 1. Search history
        res = self.client.get('/api/v1/notifications/history/?search=NullPointer')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['count'], 1)

        # 2. Filter by severity & service
        res = self.client.get('/api/v1/notifications/history/?severity=CRITICAL&service_name=auth-service')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['count'], 1)

        # 3. View full detail with traceback
        res = self.client.get(f'/api/v1/notifications/history/{notif.id}/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn('Traceback line 10', res.data['traceback'])

        # 4. Acknowledge
        res = self.client.post(f'/api/v1/notifications/history/{notif.id}/acknowledge/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        notif.refresh_from_db()
        self.assertTrue(notif.is_acknowledged)

        # 5. Resolve
        res = self.client.post(f'/api/v1/notifications/history/{notif.id}/resolve/', {
            'note': 'Fixed in hotfix v2.1.4',
        })
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        notif.refresh_from_db()
        self.assertTrue(notif.is_resolved)
        self.assertEqual(notif.resolution_note, 'Fixed in hotfix v2.1.4')

        # 6. Export CSV
        res_csv = self.client.get('/api/v1/notifications/history/export/?format=csv')
        self.assertEqual(res_csv.status_code, status.HTTP_200_OK)
        self.assertIn('text/csv', res_csv['Content-Type'])
        self.assertIn('NullPointerException in AuthService', res_csv.content.decode('utf-8'))

        # 7. Export JSON
        res_json = self.client.get('/api/v1/notifications/history/export/?format=json')
        self.assertEqual(res_json.status_code, status.HTTP_200_OK)
        self.assertIn('application/json', res_json['Content-Type'])

    # =========================================================================
    # FEATURE 6: RELIABILITY, RETRIES, DLQ & IDEMPOTENCY
    # =========================================================================
    def test_idempotency(self):
        """Test idempotency key guarantees exactly-once intake."""
        unauthed_client = APIClient()
        unauthed_client.credentials(HTTP_X_API_KEY=self.raw_key)

        idem_key = 'unique-event-id-998877'
        payload = {
            'title': 'Order Dispatched',
            'severity': Severity.INFO,
            'idempotency_key': idem_key,
        }

        res1 = unauthed_client.post('/api/v1/notifications/notify/', payload)
        self.assertEqual(res1.status_code, status.HTTP_202_ACCEPTED)
        first_id = res1.data['notification_id']

        res2 = unauthed_client.post('/api/v1/notifications/notify/', payload)
        self.assertEqual(res2.status_code, status.HTTP_200_OK)
        self.assertEqual(res2.data['notification_id'], first_id)
        self.assertEqual(res2.data['action'], 'idempotent_duplicate')

    def test_dead_letter_queue_and_reprocess(self):
        """Test Dead Letter Queue storage and reprocessing."""
        notif = Notification.objects.create(
            project=self.project,
            title='Persistent Delivery Failure Event',
            message='Could not reach server',
            severity=Severity.CRITICAL,
        )

        dlq = DeadLetterEntry.objects.create(
            notification=notif,
            channel='EMAIL',
            recipient='unreachable@example.com',
            last_error='SMTP 550 Mailbox not found',
            total_attempts=3,
        )

        # Query DLQ API
        res = self.client.get('/api/v1/delivery/dead-letter/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['count'], 1)

        # Reprocess DLQ
        with patch('delivery.tasks.deliver_notification_task.delay') as mock_deliver:
            res = self.client.post(f'/api/v1/delivery/dead-letter/{dlq.id}/reprocess/')
            self.assertEqual(res.status_code, status.HTTP_200_OK)
            dlq.refresh_from_db()
            self.assertTrue(dlq.is_reprocessed)
            mock_deliver.assert_called_once_with(str(notif.id))

    # =========================================================================
    # MULTI-SERVER / REMOTE APPLICATION TESTS
    # =========================================================================
    def test_remote_project_auto_registration_and_server_link(self):
        """Test a remote server in another project connecting simultaneously."""
        remote_client = APIClient()  # completely unauthenticated external client

        res = remote_client.post('/api/v1/notifications/notify/', {
            'project': 'Payment Gateway Microservice',
            'server_hostname': 'ec2-us-west-prod-09.internal',
            'server_ip': '192.168.1.109',
            'title': 'Stripe Circuit Breaker Tripped',
            'message': '504 gateway timeout on charge',
            'severity': Severity.CRITICAL,
            'service_name': 'payment-svc',
        })
        self.assertEqual(res.status_code, status.HTTP_202_ACCEPTED)

        # Verify project was auto-registered
        remote_proj = Project.objects.filter(name='Payment Gateway Microservice').first()
        self.assertIsNotNone(remote_proj)

        # Verify server was auto-registered under this project
        remote_server = Server.objects.filter(project=remote_proj, hostname='ec2-us-west-prod-09.internal').first()
        self.assertIsNotNone(remote_server)
        self.assertEqual(remote_server.ip_address, '192.168.1.109')

    def test_notifier_client_sdk_exception_capture(self):
        """Test NotifierClient SDK captures exception with full traceback."""
        from notifier_service.client import NotifierClient
        from unittest.mock import patch

        client = NotifierClient(endpoint='http://127.0.0.1:8000', project='OrderService', async_send=False)

        with patch.object(client, '_send_batch_request') as mock_send:
            try:
                raise ValueError("Card token expired")
            except Exception as e:
                client.capture_exception(e, service_name='billing')

            mock_send.assert_called_once()
            call_batch = mock_send.call_args[0][0]
            self.assertEqual(len(call_batch), 1)
            event = call_batch[0]
            self.assertEqual(event['error_type'], 'ValueError')
            self.assertIn('Card token expired', event['message'])
            self.assertIn('Traceback (most recent call last)', event['traceback'])
    def test_dashboard_stats_api(self):
        """Test dashboard stats endpoint produces all required metrics."""
        # Create sample data
        Notification.objects.create(
            project=self.project,
            server=self.server,
            title='Fatal Kernel Panic',
            severity=Severity.CRITICAL,
            is_resolved=False,
        )
        Notification.objects.create(
            project=self.project,
            server=self.server,
            title='Warning High Disk',
            severity=Severity.WARNING,
        )

        res = self.client.get('/api/v1/dashboard/stats/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.data

        # Check total notifications
        self.assertIn('overview', data)
        self.assertGreaterEqual(data['overview']['total_notifications'], 2)

        # Check critical errors
        self.assertIn('critical_errors', data)
        self.assertGreaterEqual(data['critical_errors']['total'], 1)
        self.assertGreaterEqual(data['critical_errors']['unresolved'], 1)

        # Check errors by project and server
        self.assertIn('errors_by_project', data)
        self.assertIn('errors_by_server', data)

        # Check delivery stats
        self.assertIn('delivery', data)
        self.assertIn('success_rate_percent', data['delivery'])

        # Check recent activity
        self.assertIn('recent_activity', data)
        self.assertGreaterEqual(len(data['recent_activity']), 1)

    # =========================================================================
    # FEATURE 7: SEVERITY FILTERING & EXCEPTION-ONLY SELECTION TESTS
    # =========================================================================
    def test_severity_filtering_and_custom_matrix(self):
        """Test default severity filtering and custom user channel matrix."""
        from delivery.tasks import resolve_channels_for_notification

        # Default fallback: WARNING and INFO return NO channels ([])
        warning_notif = Notification.objects.create(
            project=self.project,
            title='Memory Warning 75%',
            severity=Severity.WARNING,
        )
        self.assertEqual(resolve_channels_for_notification(warning_notif), [])

        info_notif = Notification.objects.create(
            project=self.project,
            title='Cron job finished',
            severity=Severity.INFO,
        )
        self.assertEqual(resolve_channels_for_notification(info_notif), [])

        # Default fallback: ERROR returns EMAIL only
        error_notif = Notification.objects.create(
            project=self.project,
            title='Database timeout',
            severity=Severity.ERROR,
            error_type='OperationalError',
        )
        self.assertEqual(resolve_channels_for_notification(error_notif), ['EMAIL'])

        # Custom matrix: User enables Telegram for WARNING
        SeverityChannelSetting.objects.create(
            project=self.project,
            severity=Severity.WARNING,
            email_enabled=False,
            telegram_enabled=True,
            whatsapp_enabled=False,
            instagram_enabled=False,
        )
        self.assertEqual(resolve_channels_for_notification(warning_notif), ['TELEGRAM'])

        # Custom matrix: User explicitly turns off ALL channels for ERROR
        SeverityChannelSetting.objects.create(
            project=self.project,
            severity=Severity.ERROR,
            email_enabled=False,
            telegram_enabled=False,
            whatsapp_enabled=False,
            instagram_enabled=False,
        )
        # Must return empty list, NOT fall back to sending email!
        self.assertEqual(resolve_channels_for_notification(error_notif), [])

    def test_notify_exceptions_only_policy(self):
        """Test that notify_exceptions_only suppresses alerts when no exception is present."""
        from delivery.tasks import resolve_channels_for_notification

        self.project.notify_exceptions_only = True
        self.project.save()

        # Regular log with ERROR severity but NO exception traceback or error_type
        regular_log = Notification.objects.create(
            project=self.project,
            title='Failed login attempt for user admin',
            severity=Severity.ERROR,
        )
        self.assertEqual(resolve_channels_for_notification(regular_log), [])

        # Log with actual exception error_type and traceback
        exception_log = Notification.objects.create(
            project=self.project,
            title='ZeroDivisionError: division by zero',
            severity=Severity.ERROR,
            error_type='ZeroDivisionError',
            traceback='Traceback (most recent call last):\n  File "app.py", line 12\nZeroDivisionError: division by zero',
        )
        self.assertEqual(resolve_channels_for_notification(exception_log), ['EMAIL'])

    def test_client_and_logging_handler_filters(self):
        """Test NotifierClient and NotifierLoggingHandler client-side filtering."""
        from notifier_service.client import NotifierClient, NotifierLoggingHandler
        import logging

        with patch.object(NotifierClient, '_send_batch_request') as mock_send:
            client = NotifierClient(
                endpoint='http://testserver',
                project='ecommerce-platform',
                async_send=False,
                notify_exceptions_only=True,
                allowed_severities=['ERROR', 'CRITICAL'],
            )

            # 1. Ignored because severity is WARNING
            client.notify(title='Warning log', severity='WARNING')
            mock_send.assert_not_called()

            # 2. Ignored because notify_exceptions_only=True and no traceback/error_type
            client.notify(title='Error without exception', severity='ERROR')
            mock_send.assert_not_called()

            # 3. Sent because it contains an actual exception
            client.notify(
                title='Error with exception',
                severity='ERROR',
                error_type='KeyError',
                traceback_str='Traceback...',
            )
            mock_send.assert_called_once()

    def test_dashboard_settings_web_view_and_api_matrix(self):
        """Test GET and POST on /settings/ web view and REST matrix API."""
        # Test web view GET
        res = self.client.get('/settings/')
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'Notification & Alert Filter Preferences')
        self.assertContains(res, 'Only Alert on Actual Exceptions')

        # Test web view POST
        post_data = {
            'project': str(self.project.id),
            'notify_exceptions_only': 'on',
            'email_CRITICAL': 'on',
            'telegram_CRITICAL': 'on',
            'email_ERROR': 'on',
            # WARNING, INFO, SUCCESS unselected
        }
        res = self.client.post('/settings/', post_data)
        self.assertEqual(res.status_code, 200)
        self.project.refresh_from_db()
        self.assertTrue(self.project.notify_exceptions_only)

        # Test REST API matrix endpoint
        res = self.client.get(f'/api/v1/notifications/severity-settings/project-matrix/?project={self.project.id}')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.data['settings']), 6)
        self.assertEqual(res.data['log_retention_days'], 15)

    def test_debug_severity_handling_and_logging_integration(self):
        """Test DEBUG severity ingestion, default silent routing, and logger mapping."""
        from delivery.tasks import resolve_channels_for_notification
        from notifier_service.client import NotifierLoggingHandler, NotifierClient
        import logging

        # 1. Verify DEBUG severity is silent by default
        debug_notif = Notification.objects.create(
            project=self.project,
            title='Diagnostic variable dump',
            severity=Severity.DEBUG,
        )
        self.assertEqual(resolve_channels_for_notification(debug_notif), [])

        # 2. Verify custom matrix allows enabling channels for DEBUG
        SeverityChannelSetting.objects.create(
            project=self.project,
            severity=Severity.DEBUG,
            email_enabled=True,
            telegram_enabled=False,
            whatsapp_enabled=False,
            instagram_enabled=False,
        )
        self.assertEqual(resolve_channels_for_notification(debug_notif), ['EMAIL'])

        # 3. Verify NotifierLoggingHandler emits DEBUG level
        with patch.object(NotifierClient, '_send_batch_request') as mock_send:
            handler = NotifierLoggingHandler(
                endpoint='http://testserver',
                project='ecommerce-platform',
                level=logging.DEBUG,
            )
            logger = logging.getLogger('test_debug_logger')
            logger.setLevel(logging.DEBUG)
            logger.addHandler(handler)

            logger.debug('Database query execution time: 0.4ms')
            handler.client.flush()

            mock_send.assert_called_once()
            call_batch = mock_send.call_args[0][0]
            self.assertEqual(call_batch[0]['severity'], 'DEBUG')
            self.assertIn('Database query execution time', call_batch[0]['message'])

    def test_log_retention_policy_and_pruning(self):
        """Test default 15-day log retention and automatic pruning mechanism."""
        from datetime import timedelta
        from django.utils import timezone
        from django.core.management import call_command
        from delivery.tasks import prune_expired_logs_task

        # 1. Verify default retention is 15 days
        self.assertEqual(self.project.log_retention_days, 15)

        now = timezone.now()
        # Notification 20 days ago (expired)
        old_notif = Notification.objects.create(
            project=self.project,
            title='Old Resolved Error',
            severity=Severity.ERROR,
            is_resolved=True,
        )
        Notification.objects.filter(pk=old_notif.pk).update(created_at=now - timedelta(days=20))

        # Notification 2 days ago (active, within 15-day window)
        recent_notif = Notification.objects.create(
            project=self.project,
            title='Recent Error',
            severity=Severity.ERROR,
            is_resolved=True,
        )
        Notification.objects.filter(pk=recent_notif.pk).update(created_at=now - timedelta(days=2))

        # Unresolved critical 25 days ago (protected by default)
        unresolved_old = Notification.objects.create(
            project=self.project,
            title='Unresolved Fatal Outage',
            severity=Severity.CRITICAL,
            is_resolved=False,
        )
        Notification.objects.filter(pk=unresolved_old.pk).update(created_at=now - timedelta(days=25))

        # 2. Test prune_expired_logs method
        pruned_count = self.project.prune_expired_logs(keep_unresolved=True)
        self.assertEqual(pruned_count, 1)  # Only old_notif deleted

        self.assertFalse(Notification.objects.filter(pk=old_notif.pk).exists())
        self.assertTrue(Notification.objects.filter(pk=recent_notif.pk).exists())
        self.assertTrue(Notification.objects.filter(pk=unresolved_old.pk).exists())

        # 3. Test management command prune_logs
        call_command('prune_logs', project=self.project.slug, include_unresolved=True)
        # Now unresolved_old is also purged because include_unresolved=True
        self.assertFalse(Notification.objects.filter(pk=unresolved_old.pk).exists())
        self.assertTrue(Notification.objects.filter(pk=recent_notif.pk).exists())

        # 4. Test Celery periodic task
        result = prune_expired_logs_task()
        self.assertIn('total_pruned', result)

        # 5. Test REST API project prune endpoint
        res = self.client.post(f'/api/v1/projects/projects/{self.project.id}/prune-logs/')
        self.assertEqual(res.status_code, 200)
        self.assertIn('pruned_count', res.data)
        self.assertEqual(res.data['log_retention_days'], 15)

        # 6. Test Settings UI updates retention days
        post_data = {
            'project': str(self.project.id),
            'log_retention_days': '30',
        }
        res = self.client.post('/settings/', post_data)
        self.assertEqual(res.status_code, 200)
        self.project.refresh_from_db()
        self.assertEqual(self.project.log_retention_days, 30)
