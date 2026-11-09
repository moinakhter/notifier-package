from django.apps import AppConfig
from django.db.backends.signals import connection_created


def configure_sqlite_pragmas(sender, connection, **kwargs):
    """
    Optimize SQLite for high-throughput concurrency:
      - WAL mode: Readers do not block writers; writers do not block readers.
      - synchronous=NORMAL: Eliminates fsync bottlenecks while maintaining crash safety in WAL.
      - busy_timeout=15000: Auto-wait up to 15s instead of throwing 'database is locked'.
      - cache_size=-64000: Allocate 64MB memory page cache.
      - temp_store=MEMORY: In-memory temp tables for fast sorting and aggregations.
    """
    if connection.vendor == 'sqlite':
        with connection.cursor() as cursor:
            cursor.execute('PRAGMA journal_mode=WAL;')
            cursor.execute('PRAGMA synchronous=NORMAL;')
            cursor.execute('PRAGMA busy_timeout=15000;')
            cursor.execute('PRAGMA cache_size=-64000;')
            cursor.execute('PRAGMA temp_store=MEMORY;')


class NotificationsConfig(AppConfig):
    name = 'notifications'

    def ready(self):
        connection_created.connect(configure_sqlite_pragmas)
