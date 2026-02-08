import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dsa_loan_management.settings')
import django
django.setup()

from django.test import RequestFactory
from core.models import User
from core.admin_views import admin_all_loans

# Get admin user
try:
    admin_user = User.objects.get(email='admindsa@gmail.com')
except:
    admin_user, _ = User.objects.get_or_create(
        email='admindsa@gmail.com',
        defaults={'username': 'admindsa', 'is_staff': True, 'is_superuser': True, 'role': 'admin'}
    )

# Create request
factory = RequestFactory()
request = factory.get('/admin/all-loans/')
request.user = admin_user

# Call view
response = admin_all_loans(request)
html = response.content.decode('utf-8', errors='ignore')

print('Status:', response.status_code)
print('Length:', len(html))
print('DOCTYPE position:', html.find('<!DOCTYPE'))
print('\nFirst 300 chars:')
print(html[:300])
