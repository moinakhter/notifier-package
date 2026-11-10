"""Channel delivery and connection test services."""
import json
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import NamedTuple
from django.utils import timezone
import requests

logger = logging.getLogger(__name__)


class DeliveryResult(NamedTuple):
    success: bool
    status_code: int | None
    response_body: str
    error_message: str


class EmailService:
    """Service for sending emails via SMTP."""

    @staticmethod
    def send(config, subject: str, body: str, recipients: list[str] | None = None) -> list[tuple[str, DeliveryResult]]:
        targets = recipients or config.recipients
        if not targets:
            return [('', DeliveryResult(False, None, '', 'No recipients configured'))]

        results = []
        try:
            if config.use_ssl:
                server = smtplib.SMTP_SSL(config.smtp_host, config.smtp_port, timeout=15)
            else:
                server = smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=15)
                if config.use_tls:
                    server.starttls()

            if config.smtp_username and config.smtp_password:
                server.login(config.smtp_username, config.smtp_password)

            for recipient in targets:
                try:
                    msg = MIMEMultipart('alternative')
                    msg['Subject'] = subject
                    msg['From'] = f'{config.from_name} <{config.from_email}>'
                    msg['To'] = recipient

                    text_part = MIMEText(body, 'plain', 'utf-8')
                    msg.attach(text_part)

                    server.sendmail(config.from_email, [recipient], msg.as_string())
                    results.append((recipient, DeliveryResult(True, 250, 'OK', '')))
                except Exception as e:
                    logger.error(f'Failed to send email to {recipient}: {e}')
                    results.append((recipient, DeliveryResult(False, None, '', str(e))))

            server.quit()
        except Exception as e:
            logger.error(f'SMTP connection failure to {config.smtp_host}:{config.smtp_port} - {e}')
            for r in targets:
                results.append((r, DeliveryResult(False, None, '', f'SMTP Connection Error: {e}')))

        return results

    @classmethod
    def test_connection(cls, config, send_test_email: bool = False, recipient: str | None = None) -> tuple[bool, str]:
        """Test SMTP server connectivity and authentication, optionally sending a test email."""
        try:
            if config.use_ssl:
                server = smtplib.SMTP_SSL(config.smtp_host, config.smtp_port, timeout=10)
            else:
                server = smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=10)
                if config.use_tls:
                    server.starttls()

            if config.smtp_username and config.smtp_password:
                server.login(config.smtp_username, config.smtp_password)

            target = recipient or (config.recipients[0] if (hasattr(config, 'recipients') and config.recipients) else None)
            if send_test_email and target:
                msg = MIMEMultipart('alternative')
                msg['Subject'] = '✅ [Notifier Service] Test Email Verification'
                msg['From'] = f'{getattr(config, "from_name", "Notifier Service")} <{config.from_email}>'
                msg['To'] = target

                proj_name = getattr(config.project, 'name', 'Notifier Hub') if hasattr(config, 'project') and config.project else 'Notifier Hub'
                body = (
                    "Hello,\n\n"
                    "This is an automated test email from your Notifier Service Hub.\n"
                    "Your SMTP email configuration is functioning correctly and is ready to deliver alerts!\n\n"
                    f"Project: {proj_name}\n"
                    f"SMTP Host: {config.smtp_host}:{config.smtp_port}\n"
                    f"Timestamp: {timezone.now().strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n"
                    "— Notifier Service Hub"
                )
                msg.attach(MIMEText(body, 'plain', 'utf-8'))
                server.sendmail(config.from_email, [target], msg.as_string())
                server.quit()
                return True, f'SMTP verified! Test email successfully sent to {target}. Check your inbox.'

            server.noop()
            server.quit()
            return True, 'SMTP connection and authentication successful'
        except Exception as e:
            return False, f'SMTP test failed: {e}'


class TelegramService:
    """Service for sending messages via Telegram Bot API."""

    BASE_URL = 'https://api.telegram.org'

    @classmethod
    def send(cls, config, message: str, chat_ids: list[str] | None = None) -> list[tuple[str, DeliveryResult]]:
        targets = chat_ids or config.chat_ids
        if not targets:
            return [('', DeliveryResult(False, None, '', 'No chat IDs configured'))]

        url = f'{cls.BASE_URL}/bot{config.bot_token}/sendMessage'
        results = []

        for chat_id in targets:
            payload = {
                'chat_id': chat_id,
                'text': message,
                'parse_mode': config.parse_mode,
            }
            try:
                resp = requests.post(url, json=payload, timeout=10)
                success = resp.status_code == 200 and resp.json().get('ok', False)
                err = '' if success else resp.text
                results.append((chat_id, DeliveryResult(success, resp.status_code, resp.text, err)))
            except Exception as e:
                logger.error(f'Telegram send error for chat {chat_id}: {e}')
                results.append((chat_id, DeliveryResult(False, None, '', str(e))))

        return results

    @classmethod
    def test_connection(cls, config) -> tuple[bool, str]:
        """Verify bot token via getMe endpoint."""
        url = f'{cls.BASE_URL}/bot{config.bot_token}/getMe'
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200 and resp.json().get('ok', False):
                bot_user = resp.json().get('result', {}).get('username', 'Bot')
                return True, f'Connected to Telegram bot: @{bot_user}'
            return False, f'Telegram verification failed: {resp.text}'
        except Exception as e:
            return False, f'Telegram connection error: {e}'


class WhatsAppService:
    """Service for sending messages via WhatsApp Cloud API."""

    BASE_URL = 'https://graph.facebook.com'

    @classmethod
    def send(cls, config, text: str, recipient_numbers: list[str] | None = None) -> list[tuple[str, DeliveryResult]]:
        targets = recipient_numbers or config.recipient_numbers
        if not targets:
            return [('', DeliveryResult(False, None, '', 'No WhatsApp recipient numbers configured'))]

        version = config.api_version or 'v21.0'
        url = f'{cls.BASE_URL}/{version}/{config.phone_number_id}/messages'
        headers = {
            'Authorization': f'Bearer {config.access_token}',
            'Content-Type': 'application/json',
        }
        results = []

        for recipient in targets:
            payload = {
                'messaging_product': 'whatsapp',
                'recipient_type': 'individual',
                'to': recipient,
                'type': 'text',
                'text': {'body': text},
            }
            try:
                resp = requests.post(url, headers=headers, json=payload, timeout=10)
                success = 200 <= resp.status_code < 300
                err = '' if success else resp.text
                results.append((recipient, DeliveryResult(success, resp.status_code, resp.text, err)))
            except Exception as e:
                logger.error(f'WhatsApp send error to {recipient}: {e}')
                results.append((recipient, DeliveryResult(False, None, '', str(e))))

        return results

    @classmethod
    def test_connection(cls, config) -> tuple[bool, str]:
        """Verify WhatsApp Phone Number ID and Access Token."""
        version = config.api_version or 'v21.0'
        url = f'{cls.BASE_URL}/{version}/{config.phone_number_id}'
        headers = {'Authorization': f'Bearer {config.access_token}'}
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            if 200 <= resp.status_code < 300:
                data = resp.json()
                verified_name = data.get('verified_name', data.get('display_phone_number', 'WhatsApp Account'))
                return True, f'WhatsApp connected successfully: {verified_name}'
            return False, f'WhatsApp verification failed: {resp.text}'
        except Exception as e:
            return False, f'WhatsApp connection error: {e}'


class InstagramService:
    """Service for sending messages via Instagram Messaging API."""

    BASE_URL = 'https://graph.facebook.com'

    @classmethod
    def send(cls, config, text: str, recipient_ids: list[str] | None = None) -> list[tuple[str, DeliveryResult]]:
        targets = recipient_ids or config.recipient_ids
        if not targets:
            return [('', DeliveryResult(False, None, '', 'No Instagram recipient IDs configured'))]

        version = config.api_version or 'v21.0'
        url = f'{cls.BASE_URL}/{version}/me/messages'
        headers = {
            'Authorization': f'Bearer {config.access_token}',
            'Content-Type': 'application/json',
        }
        results = []

        for recipient_id in targets:
            payload = {
                'recipient': {'id': recipient_id},
                'message': {'text': text},
            }
            try:
                resp = requests.post(url, headers=headers, json=payload, timeout=10)
                success = 200 <= resp.status_code < 300
                err = '' if success else resp.text
                results.append((recipient_id, DeliveryResult(success, resp.status_code, resp.text, err)))
            except Exception as e:
                logger.error(f'Instagram send error to {recipient_id}: {e}')
                results.append((recipient_id, DeliveryResult(False, None, '', str(e))))

        return results

    @classmethod
    def test_connection(cls, config) -> tuple[bool, str]:
        """Verify Instagram account ID and access token."""
        version = config.api_version or 'v21.0'
        url = f'{cls.BASE_URL}/{version}/{config.instagram_account_id}'
        headers = {'Authorization': f'Bearer {config.access_token}'}
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            if 200 <= resp.status_code < 300:
                data = resp.json()
                username = data.get('username', data.get('name', 'Instagram Account'))
                return True, f'Instagram connected successfully: @{username}'
            return False, f'Instagram verification failed: {resp.text}'
        except Exception as e:
            return False, f'Instagram connection error: {e}'
