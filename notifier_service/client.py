"""
Client SDK for Notifier Service.
Allows any external project hosted on any server to send alerts and notifications
to a central Notifier Service instance seamlessly and without blocking.
"""
import logging
import platform
import socket
import sys
import threading
import traceback
from typing import Any
import requests

logger = logging.getLogger(__name__)


class NotifierClient:
    """
    Lightweight, thread-safe, non-blocking client for sending notifications
    from any application on any server to a central Notifier Service instance.
    """

    def __init__(
        self,
        endpoint: str = 'http://127.0.0.1:8000',
        project: str = 'default-project',
        api_key: str | None = None,
        timeout: float = 4.0,
        async_send: bool = True,
        server_hostname: str | None = None,
    ):
        self.endpoint = endpoint.rstrip('/')
        self.notify_url = f'{self.endpoint}/api/v1/notifications/notify/'
        self.project = project
        self.api_key = api_key
        self.timeout = timeout
        self.async_send = async_send
        self.server_hostname = server_hostname or socket.gethostname() or platform.node()

    def _get_headers(self) -> dict[str, str]:
        headers = {'Content-Type': 'application/json'}
        if self.api_key:
            headers['X-API-Key'] = self.api_key
        return headers

    def _do_send(self, payload: dict[str, Any]) -> dict | None:
        try:
            resp = requests.post(
                self.notify_url,
                json=payload,
                headers=self._get_headers(),
                timeout=self.timeout,
            )
            if 200 <= resp.status_code < 300:
                return resp.json()
            logger.warning(f'Notifier server returned status {resp.status_code}: {resp.text[:200]}')
        except Exception as e:
            logger.warning(f'Failed to deliver notification to {self.notify_url}: {e}')
        return None

    def notify(
        self,
        title: str,
        message: str = '',
        severity: str = 'ERROR',
        service_name: str = '',
        error_type: str = '',
        traceback_str: str = '',
        context: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        template_name: str | None = None,
    ) -> None:
        """
        Send a notification to the central Notifier Service.
        Executes in a background thread if async_send is True (default).
        """
        payload = {
            'title': title,
            'message': message,
            'severity': severity.upper(),
            'project': self.project,
            'service_name': service_name,
            'server_hostname': self.server_hostname,
            'error_type': error_type,
            'traceback': traceback_str,
            'context': context or {},
            'idempotency_key': idempotency_key,
            'template_name': template_name,
        }

        if self.async_send:
            t = threading.Thread(target=self._do_send, args=(payload,), daemon=True)
            t.start()
        else:
            self._do_send(payload)

    def capture_exception(
        self,
        exc: BaseException,
        title: str | None = None,
        severity: str = 'CRITICAL',
        service_name: str = '',
        context: dict[str, Any] | None = None,
    ) -> None:
        """
        Automatically format and send an uncaught Python exception with full traceback.
        """
        tb = ''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        err_type = type(exc).__name__
        err_title = title or f'{err_type}: {str(exc)[:120]}'

        self.notify(
            title=err_title,
            message=str(exc),
            severity=severity,
            service_name=service_name,
            error_type=err_type,
            traceback_str=tb,
            context=context,
        )


class NotifierLoggingHandler(logging.Handler):
    """
    Standard Python logging.Handler to direct logger.error() and logger.critical()
    records from any server straight to the central Notifier Service.
    """

    def __init__(
        self,
        endpoint: str = 'http://127.0.0.1:8000',
        project: str = 'default-project',
        api_key: str | None = None,
        service_name: str = '',
        level: int = logging.ERROR,
    ):
        super().__init__(level=level)
        self.client = NotifierClient(
            endpoint=endpoint,
            project=project,
            api_key=api_key,
            async_send=True,
        )
        self.service_name = service_name

    def emit(self, record: logging.LogRecord):
        try:
            msg = self.format(record)
            sev = 'CRITICAL' if record.levelno >= logging.CRITICAL else 'ERROR'
            if record.levelno == logging.WARNING:
                sev = 'WARNING'
            elif record.levelno == logging.INFO:
                sev = 'INFO'

            tb = ''
            err_type = ''
            if record.exc_info:
                exc_type, exc_val, exc_tb = record.exc_info
                tb = ''.join(traceback.format_exception(exc_type, exc_val, exc_tb))
                err_type = exc_type.__name__ if exc_type else ''

            self.client.notify(
                title=f'[{record.name}] {record.getMessage()[:150]}',
                message=msg,
                severity=sev,
                service_name=self.service_name or record.name,
                error_type=err_type,
                traceback_str=tb,
                context={
                    'filename': record.filename,
                    'lineno': record.lineno,
                    'funcName': record.funcName,
                },
            )
        except Exception:
            self.handleError(record)
