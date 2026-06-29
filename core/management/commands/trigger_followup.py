"""
Management command to automatically move Banking Login Process applications
to Follow Up after 4+ hours in banking status.
"""
from django.core.management.base import BaseCommand

from core.followup_utils import auto_move_overdue_to_follow_up


class Command(BaseCommand):
    help = 'Automatically move Banking Login Process applications to Follow Up after 4 hours'

    def handle(self, *args, **options):
        moved = auto_move_overdue_to_follow_up()
        app_count = moved.get('applications_to_follow_up_pending', 0)
        loan_count = moved.get('loans_to_follow_up_pending', 0)
        total = app_count + loan_count
        self.stdout.write(
            self.style.SUCCESS(
                f'\nProcessed banking follow-up automation: '
                f'{app_count} application(s), {loan_count} legacy loan(s), {total} total'
            )
        )
