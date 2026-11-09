"""
Client SDK for Notifier Service.
Allows any external project hosted on any server to send alerts and notifications
to a central Notifier Service instance seamlessly and without blocking.
"""
import atexit
import logging
import platform
import queue
import socket
import sys
import threading
import time
import traceback
from typing import Any
import requests

logger = logging.getLogger(__name__)


class NotifierClient:
    """
    Lightweight, thread-safe, high-throughput non-blocking client.
    Uses an in-memory queue and background batch worker capable of
    absorbing thousands of logs/second with microsecond call latency.
    """

    def __init__(
        self,
        endpoint: str = 'http://127.0.0.1:8000',
        project: str = 'default-project',
        api_key: str | None = None,
        timeout: float = 5.0,
        async_send: bool = True,
        batch_size: int = 200,
        flush_interval: float = 0.05,
        server_hostname: str | None = None,
        notify_exceptions_only: bool = False,
        allowed_severities: list[str] | tuple[str, ...] | None = None,
    ):
        self.endpoint = endpoint.rstrip('/')
        self.notify_url = f'{self.endpoint}/api/v1/notifications/notify/'
        self.batch_url = f'{self.endpoint}/api/v1/notifications/batch/'
        self.project = project
        self.api_key = api_key
        self.timeout = timeout
        self.async_send = async_send
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.server_hostname = server_hostname or socket.gethostname() or platform.node()
        self.notify_exceptions_only = notify_exceptions_only
        self.allowed_severities = [s.upper() for s in allowed_severities] if allowed_severities else None

        # In-memory buffer queue for high-throughput zero-latency logging
        self._queue = queue.Queue(maxsize=100000)
        self._stop_event = threading.Event()

        if self.async_send:
            self._worker_thread = threading.Thread(target=self._flusher_loop, daemon=True)
            self._worker_thread.start()
            atexit.register(self.flush, timeout=2.0)

    def _get_headers(self) -> dict[str, str]:
        headers = {'Content-Type': 'application/json'}
        if self.api_key:
            headers['X-API-Key'] = self.api_key
        return headers

    def _send_batch_request(self, batch: list[dict[str, Any]]) -> dict | None:
        """Post a batch of log events to the central Notifier Service."""
        if not batch:
            return None
        payload = {
            'project': self.project,
            'server_hostname': self.server_hostname,
            'events': batch,
        }
        try:
            resp = requests.post(
                self.batch_url,
                json=payload,
                headers=self._get_headers(),
                timeout=self.timeout,
            )
            if 200 <= resp.status_code < 300:
                return resp.json()
            logger.warning(f'Notifier batch returned {resp.status_code}: {resp.text[:150]}')
        except Exception as e:
            logger.warning(f'Batch delivery failed to {self.batch_url}: {e}')
        return None

    def _flusher_loop(self):
        """Background daemon thread draining queue in high-speed batches."""
        while not self._stop_event.is_set():
            batch = []
            try:
                # Wait for first item
                item = self._queue.get(timeout=self.flush_interval)
                batch.append(item)
                self._queue.task_done()

                # Drain more items up to batch_size without waiting
                while len(batch) < self.batch_size:
                    try:
                        item = self._queue.get_nowait()
                        batch.append(item)
                        self._queue.task_done()
                    except queue.Empty:
                        break

            except queue.Empty:
                pass

            if batch:
                self._send_batch_request(batch)

    def flush(self, timeout: float = 3.0) -> None:
        """Drain all remaining in-flight events before shutdown."""
        start = time.time()
        while not self._queue.empty() and (time.time() - start < timeout):
            batch = []
            while len(batch) < self.batch_size and not self._queue.empty():
                try:
                    batch.append(self._queue.get_nowait())
                    self._queue.task_done()
                except queue.Empty:
                    break
            if batch:
                self._send_batch_request(batch)

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
        Record a notification.
        If async_send is True, places into queue with ~0.005ms latency.
        """
        sev_upper = severity.upper()
        if self.allowed_severities and sev_upper not in self.allowed_severities:
            return

        if self.notify_exceptions_only:
            has_exc = bool(traceback_str or error_type or (context and ('exception' in context or 'traceback' in context)))
            if not has_exc:
                return

        payload = {
            'title': title,
            'message': message,
            'severity': sev_upper,
            'service_name': service_name,
            'error_type': error_type,
            'traceback': traceback_str,
            'context': context or {},
            'idempotency_key': idempotency_key,
            'template_name': template_name,
        }

        if self.async_send:
            try:
                self._queue.put_nowait(payload)
            except queue.Full:
                logger.warning('Notifier buffer queue is full. Dropping log.')
        else:
            self._send_batch_request([payload])

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
    Standard Python logging.Handler directing logger records across all servers
    straight to the central Notifier Service without blocking caller threads.
    """

    def __init__(
        self,
        endpoint: str = 'http://127.0.0.1:8000',
        project: str = 'default-project',
        api_key: str | None = None,
        service_name: str = '',
        level: int = logging.ERROR,
        notify_exceptions_only: bool = False,
        allowed_severities: list[str] | tuple[str, ...] | None = None,
    ):
        super().__init__(level=level)
        self.notify_exceptions_only = notify_exceptions_only
        self.allowed_severities = [s.upper() for s in allowed_severities] if allowed_severities else None
        self.client = NotifierClient(
            endpoint=endpoint,
            project=project,
            api_key=api_key,
            async_send=True,
            notify_exceptions_only=notify_exceptions_only,
            allowed_severities=self.allowed_severities,
        )
        self.service_name = service_name

    def emit(self, record: logging.LogRecord):
        try:
            if self.notify_exceptions_only and not record.exc_info:
                return

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
