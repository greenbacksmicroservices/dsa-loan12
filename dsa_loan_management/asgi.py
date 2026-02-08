"""
ASGI config for dsa_loan_management project.
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dsa_loan_management.settings')

application = get_asgi_application()


