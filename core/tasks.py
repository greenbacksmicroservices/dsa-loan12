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
    Check for applications waiting > 4 hours and move to follow-up status.
    Runs every 1 hour via Celery beat.
    """
    try:
        # Get current time minus 4 hours
        cutoff_time = timezone.now() - timedelta(hours=4)
        
        # Find applications that are "Waiting for Processing" and older than 4 hours
        applications_needing_followup = LoanApplication.objects.filter(
            status='Waiting for Processing',
            assigned_at__lt=cutoff_time,
            assigned_at__isnull=False
        ).exclude(
            follow_up_scheduled_at__isnull=False
        )
        
        updated_count = 0
        
        for application in applications_needing_followup:
            try:
                # Move to Required Follow-up
                application.trigger_follow_up()
                
                # Get assigned user for notification
                assigned_user = application.assigned_employee or (
                    application.assigned_agent.user if application.assigned_agent else None
                )
                
                # Get admin user for notification
                admin_users = User.objects.filter(role='admin')
                
                # Create activity log
                ActivityLog.objects.create(
                    action='follow_up_triggered',
                    description=f"Application {application.applicant.full_name} moved to Required Follow-up (4+ hours waiting)",
                    user=None,  # System action
                )
                
                # Send notifications
                send_follow_up_notifications(application, assigned_user, admin_users)
                
                updated_count += 1
                logger.info(f"Follow-up triggered for application {application.id}: {application.applicant.full_name}")
                
            except Exception as e:
                logger.error(f"Error processing application {application.id}: {str(e)}")
                continue
        
        logger.info(f"Follow-up check completed: {updated_count} applications moved to follow-up status")
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
        """APScheduler version of follow-up check"""
        try:
            from django.utils import timezone
            from datetime import timedelta
            
            cutoff_time = timezone.now() - timedelta(hours=4)
            applications_needing_followup = LoanApplication.objects.filter(
                status='Waiting for Processing',
                assigned_at__lt=cutoff_time,
                assigned_at__isnull=False,
                follow_up_scheduled_at__isnull=True
            )
            
            updated_count = 0
            for application in applications_needing_followup:
                application.trigger_follow_up()
                updated_count += 1
                
                ActivityLog.objects.create(
                    action='follow_up_triggered',
                    description=f"Application {application.applicant.full_name} moved to Required Follow-up"
                )
            
            logger.info(f"APScheduler: {updated_count} applications moved to follow-up")
            return updated_count
            
        except Exception as e:
            logger.error(f"APScheduler error: {str(e)}")
            return 0
