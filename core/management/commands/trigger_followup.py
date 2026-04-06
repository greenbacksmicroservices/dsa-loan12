"""
Management command to automatically trigger follow-up for loan applications
that have been in "Waiting for Processing" status for 4+ hours
without action by assigned employee
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from core.models import LoanApplication, ActivityLog

class Command(BaseCommand):
    help = 'Automatically move loan applications to Required Follow-up after 4 hours without action'

    def handle(self, *args, **options):
        now = timezone.now()
        cutoff_time = now - timedelta(hours=4)
        
        # Find all loan applications that:
        # 1. Are in "Waiting for Processing" status
        # 2. Were assigned more than 4 hours ago
        # 3. Have not been approved, rejected, or already moved to follow-up
        overdue_applications = LoanApplication.objects.filter(
            status='Waiting for Processing',
            assigned_at__lte=cutoff_time,
            approved_at__isnull=True,
            rejected_at__isnull=True,
        )
        
        count = 0
        for app in overdue_applications:
            try:
                # Move to Required Follow-up
                app.trigger_follow_up()
                
                # Log the activity
                ActivityLog.objects.create(
                    action='auto_followup_triggered',
                    description=f'Automatic follow-up triggered for {app.applicant.full_name} after 4 hours without action',
                )
                
                count += 1
                self.stdout.write(
                    self.style.SUCCESS(f'✓ {app.applicant.full_name} moved to Required Follow-up')
                )
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f'✗ Error processing {app.applicant.full_name}: {str(e)}')
                )
        
        self.stdout.write(
            self.style.SUCCESS(f'\n✓ Successfully processed {count} applications for follow-up')
        )
