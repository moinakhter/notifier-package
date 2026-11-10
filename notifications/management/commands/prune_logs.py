"""
Management command to prune notification logs older than project retention policy (default: 15 days).
Usage:
    python manage.py prune_logs
    python manage.py prune_logs --days=30
    python manage.py prune_logs --project=ecommerce-platform
    python manage.py prune_logs --include-unresolved
"""
from django.core.management.base import BaseCommand
from projects.models import Project


class Command(BaseCommand):
    help = 'Prunes notification logs older than the configured retention policy (default: 15 days).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=None,
            help='Override the retention days threshold for this run.',
        )
        parser.add_argument(
            '--project',
            type=str,
            default=None,
            help='Target a specific project by slug, name, or UUID.',
        )
        parser.add_argument(
            '--include-unresolved',
            action='store_true',
            default=False,
            help='Also prune unresolved critical/error notifications (default preserves them).',
        )

    def handle(self, *args, **options):
        days_override = options.get('days')
        proj_identifier = options.get('project')
        include_unresolved = options.get('include_unresolved', False)
        keep_unresolved = not include_unresolved

        if proj_identifier:
            proj = (
                Project.objects.filter(slug=proj_identifier).first()
                or Project.objects.filter(name__iexact=proj_identifier).first()
            )
            if not proj:
                try:
                    import uuid as _uuid
                    _uuid.UUID(proj_identifier)
                    proj = Project.objects.filter(id=proj_identifier).first()
                except (ValueError, AttributeError):
                    pass

            if not proj:
                self.stderr.write(self.style.ERROR(f'Project "{proj_identifier}" not found.'))
                return

            original_days = proj.log_retention_days
            if days_override is not None:
                proj.log_retention_days = max(0, days_override)

            deleted = proj.prune_expired_logs(keep_unresolved=keep_unresolved)
            effective_days = proj.log_retention_days
            self.stdout.write(
                self.style.SUCCESS(
                    f'Successfully pruned {deleted} logs for project "{proj.name}" '
                    f'(retention threshold: {effective_days} days).'
                )
            )
            return

        # Prune all projects
        projects = Project.objects.filter(is_active=True)
        total_deleted = 0
        for p in projects:
            if days_override is not None:
                p.log_retention_days = max(0, days_override)
            count = p.prune_expired_logs(keep_unresolved=keep_unresolved)
            if count > 0:
                self.stdout.write(f'  - {p.name}: {count} logs pruned (retention: {p.log_retention_days} days)')
                total_deleted += count

        self.stdout.write(
            self.style.SUCCESS(
                f'Done! Total {total_deleted} expired notification logs pruned across all projects.'
            )
        )
