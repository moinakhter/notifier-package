"""
Notifier Service - Free, open, multi-channel notification and alert dispatching engine.
Zero-configuration SQLite default, no authentication required.
"""

from .client import NotifierClient, NotifierLoggingHandler
from .middleware import NotifierExceptionMiddleware

__version__ = "1.0.1"
__author__ = "Notifier Service Authors"
__license__ = "MIT"

__all__ = [
    "NotifierClient",
    "NotifierLoggingHandler",
    "NotifierExceptionMiddleware",
]
