"""
Move Bank Login Process loans to Follow Up after 4+ hours.

Schedule every 5-10 minutes, e.g.:
*/10 * * * * /var/www/dsa/venv/bin/python /var/www/dsa/dsa-loan12/manage.py move_banking_process_to_followup
"""
from django.core.management.base import BaseCommand

from core.followup_utils import auto_move_overdue_to_follow_up, backfill_banking_processing_timestamps


class Command(BaseCommand):
    help = 'Move Banking Login Process loans to Follow Up after 4 hours'

    def handle(self, *args, **options):
        backfilled = backfill_banking_processing_timestamps()
        moved = auto_move_overdue_to_follow_up()
        app_count = moved.get('applications_to_follow_up_pending', 0)
        loan_count = moved.get('loans_to_follow_up_pending', 0)
        total = app_count + loan_count
        self.stdout.write(
            self.style.SUCCESS(
                f'Backfilled timestamps: {backfilled.get("applications", 0)} application(s), '
                f'{backfilled.get("loans", 0)} legacy loan(s). '
                f'Moved to Follow Up: {app_count} application(s), {loan_count} legacy loan(s), {total} total.'
            )
        )
