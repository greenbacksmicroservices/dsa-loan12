"""
Celery configuration for DSA Loan Management System.
Sets up distributed task queue for background jobs and scheduled tasks.
"""

import os
from celery import Celery
from celery.schedules import crontab
from django.conf import settings

# Set default Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dsa_loan_management.settings')

# Create Celery app
app = Celery('dsa_loan_management')

# Load config from Django settings
app.config_from_object('django.conf:settings', namespace='CELERY')

# Auto-discover tasks from all installed apps
app.autodiscover_tasks()

# Optional: Configure logging for Celery tasks
import logging
logger = logging.getLogger(__name__)


@app.task(bind=True)
def debug_task(self):
    """Debug task to test Celery setup"""
    print(f'Request: {self.request!r}')
    logger.info('Debug task executed successfully')
    return 'Debug task completed'


# Additional configuration for production
if settings.DEBUG:
    # Development settings
    app.conf.update(
        CELERY_ALWAYS_EAGER=False,  # Actually run tasks asynchronously in dev
        CELERY_EAGER_PROPAGATES_EXCEPTIONS=True,
    )
else:
    # Production settings
    app.conf.update(
        CELERY_ALWAYS_EAGER=False,
        CELERY_EAGER_PROPAGATES_EXCEPTIONS=False,
        CELERYD_POOL='prefork',
        CELERYD_CONCURRENCY=4,
    )
