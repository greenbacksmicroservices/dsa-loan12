import os
import django
import sys

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dsa_loan_management.settings')
django.setup()

from django.test import Client
from core.models import User

client = Client()

# Get or create admin user
user, created = User.objects.get_or_create(
    email='admindsa@gmail.com',
    defaults={'password': 'admin123', 'role': 'admin', 'is_active': True}
)

# Force login
client.force_login(user)

try:
    response = client.get('/admin/all-loans/')
    print(f'Status: {response.status_code}')
    print(f'Content length: {len(response.content)}')
    if len(response.content) > 0:
        print(f'First 200 chars: {response.content[:200]}')
except Exception as e:
    print(f'Error: {e}')
    import traceback
    traceback.print_exc()
