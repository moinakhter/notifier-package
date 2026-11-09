"""Command-line interface for Notifier Service."""
import os
import sys


def main():
    """CLI entrypoint for running notifier-service commands."""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable?"
        ) from exc

    if len(sys.argv) == 1:
        # Default action: migrate SQLite and start server on 0.0.0.0:8000
        print("=" * 60)
        print("  Notifier Service v1.0.2 (Free & Open Source)")
        print("  Database: SQLite (default)")
        print("  Authentication: Disabled (Open access)")
        print("  Dashboard: http://127.0.0.1:8000/")
        print("  API Docs:  http://127.0.0.1:8000/api/v1/")
        print("=" * 60)
        try:
            execute_from_command_line([sys.argv[0], 'migrate', '--noinput'])
        except Exception as e:
            print(f"Note on migrations: {e}")
        execute_from_command_line([sys.argv[0], 'runserver', '0.0.0.0:8000'])
    else:
        execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
