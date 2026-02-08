"""
Signals for automatic workflow management
- Auto-trigger follow-up after 24 hours
- Track status changes
"""
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.utils import timezone
from datetime import timedelta
from .models import LoanApplication, ActivityLog

@receiver(post_save, sender=LoanApplication)
def handle_loan_application_status_change(sender, instance, created, **kwargs):
    """
    Handle loan application status changes and track assignment time
    """
    if not created and instance.status == 'Waiting for Processing':
        # If status changed to 'Waiting for Processing', ensure assigned_at is set
        if not instance.assigned_at:
            instance.assigned_at = timezone.now()
            instance.save(update_fields=['assigned_at'])

def check_and_trigger_followups():
    """
    Check all waiting loan applications and move to follow-up if 24 hours have passed
    This should be run periodically (via celery beat or cron job)
    """
    now = timezone.now()
    cutoff_time = now - timedelta(hours=24)
    
    # Find overdue applications that are still waiting
    overdue_applications = LoanApplication.objects.filter(
        status='Waiting for Processing',
        assigned_at__lte=cutoff_time,
        approved_at__isnull=True,
        rejected_at__isnull=True,
    )
    
    count = 0
    for app in overdue_applications:
        try:
            # Use the trigger_follow_up method from the model
            app.trigger_follow_up()
            
            # Log activity
            ActivityLog.objects.create(
                action='auto_followup_triggered',
                description=f'Automatic follow-up triggered for {app.applicant.full_name} after 24 hours without action',
            )
            
            count += 1
        except Exception as e:
            print(f'Error triggering follow-up for {app.applicant.full_name}: {str(e)}')
    
    return count

                description=f'Auto follow-up triggered for {loan.full_name} (24 hours without action)',
                applicant_id=loan.id
            )
            
            count += 1
        except Exception as e:
            print(f'Error triggering follow-up for loan {loan.id}: {str(e)}')
    
    return count

# Import this in apps.py and call periodically
