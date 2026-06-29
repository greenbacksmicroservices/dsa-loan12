# Celery Tasks for Loan Application Workflow Automation
"""
Automated workflow tasks:
- Check for 4-hour old waiting applications
- Move to Required Follow-up status
- Send notifications
- Log activities
"""

from celery import shared_task
from django.utils import timezone
from django.core.mail import send_mail
from django.conf import settings
from datetime import timedelta
from .models import LoanApplication, ActivityLog, User

import logging

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def check_and_trigger_follow_ups(self):
    """
    Move Banking Login Process applications to Follow Up after 4 hours.
    Runs periodically via Celery beat.
    """
    try:
        from .followup_utils import auto_move_overdue_to_follow_up

        moved = auto_move_overdue_to_follow_up()
        updated_count = (
            moved.get('applications_to_follow_up_pending', 0)
            + moved.get('loans_to_follow_up_pending', 0)
        )

        logger.info(
            'Banking follow-up check completed: %s record(s) moved to Follow Up',
            updated_count,
        )
        return {
            'status': 'success',
            'applications_updated': updated_count,
            'timestamp': timezone.now().isoformat()
        }

    except Exception as exc:
        logger.error(f"Error in check_and_trigger_follow_ups: {str(exc)}")
        # Retry after 5 minutes
        raise self.retry(countdown=300, exc=exc)


def send_follow_up_notifications(application, assigned_user, admin_users):
    """Send email notifications when follow-up is triggered"""
    try:
        applicant_name = application.applicant.full_name
        applicant_email = application.applicant.email
        
        # Notify assigned employee/agent
        if assigned_user and assigned_user.email:
            subject = f"Follow-up Required: {applicant_name} Loan Application"
            message = f"""
            Hello {assigned_user.first_name},
            
            The loan application for {applicant_name} has been waiting for processing for over 4 hours.
            
            Loan Details:
            - Applicant: {applicant_name}
            - Loan Type: {application.applicant.get_loan_type_display()}
            - Loan Amount: ₹{application.applicant.loan_amount}
            - Status: Required Follow-up
            
            Please review and take action as soon as possible.
            
            Best regards,
            DSA Loan Management System
            """
            
            send_mail(
                subject,
                message,
                settings.DEFAULT_FROM_EMAIL,
                [assigned_user.email],
                fail_silently=True
            )
        
        # Notify all admins
        for admin_user in admin_users:
            if admin_user.email:
                subject = f"ALERT: Follow-up Required - {applicant_name}"
                message = f"""
                SYSTEM ALERT: 4-Hour Follow-up Triggered
                
                Application: {applicant_name}
                Loan Type: {application.applicant.get_loan_type_display()}
                Amount: ₹{application.applicant.loan_amount}
                
                Assigned To: {assigned_user.first_name if assigned_user else 'Unassigned'}
                Status: Required Follow-up
                
                Please monitor this application.
                
                System Generated Alert
                """
                
                send_mail(
                    subject,
                    message,
                    settings.DEFAULT_FROM_EMAIL,
                    [admin_user.email],
                    fail_silently=True
                )
                
    except Exception as e:
        logger.error(f"Error sending notifications: {str(e)}")


@shared_task
def log_workflow_event(application_id, action, description, user_id=None):
    """
    Log workflow events for audit trail.
    Called after each workflow action.
    """
    try:
        from django.contrib.auth import get_user_model
        User = get_user_model()
        
        user = User.objects.get(id=user_id) if user_id else None
        application = LoanApplication.objects.get(id=application_id)
        
        ActivityLog.objects.create(
            action=action,
            description=f"[{application.applicant.full_name}] {description}",
            user=user,
        )
        
        return f"Event logged: {action}"
    except Exception as e:
        logger.error(f"Error logging event: {str(e)}")
        return f"Error: {str(e)}"


@shared_task
def generate_dashboard_stats():
    """
    Generate daily dashboard statistics.
    Runs once per day via Celery beat.
    """
    try:
        stats = {
            'new_entries': LoanApplication.objects.filter(status='New Entry').count(),
            'waiting': LoanApplication.objects.filter(status='Waiting for Processing').count(),
            'follow_up': LoanApplication.objects.filter(status='Required Follow-up').count(),
            'approved': LoanApplication.objects.filter(status='Approved').count(),
            'rejected': LoanApplication.objects.filter(status='Rejected').count(),
            'timestamp': timezone.now().isoformat(),
        }
        
        logger.info(f"Dashboard stats: {stats}")
        return stats
        
    except Exception as e:
        logger.error(f"Error generating dashboard stats: {str(e)}")
        return None


# Alternative: Using APScheduler (if Celery not available)
class WorkflowScheduler:
    """APScheduler-based task scheduler as alternative to Celery"""
    
    @staticmethod
    def check_follow_ups_apscheduler():
        """APScheduler version of banking follow-up aging."""
        try:
            from .followup_utils import auto_move_overdue_to_follow_up

            moved = auto_move_overdue_to_follow_up()
            updated_count = (
                moved.get('applications_to_follow_up_pending', 0)
                + moved.get('loans_to_follow_up_pending', 0)
            )
            logger.info(f"APScheduler: {updated_count} record(s) moved to Follow Up")
            return updated_count

        except Exception as e:
            logger.error(f"APScheduler error: {str(e)}")
            return 0
