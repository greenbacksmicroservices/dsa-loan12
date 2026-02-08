import os
import django
import sys

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dsa_loan_management.settings')
django.setup()

from django.test import Client
from core.models import User
import logging

logging.basicConfig(level=logging.DEBUG)

client = Client()

user, created = User.objects.get_or_create(
    email='admindsa@gmail.com',
    defaults={'password': 'admin123', 'role': 'admin', 'is_active': True}
)

client.force_login(user)

print('Attempting to GET /admin/all-loans/')
try:
    response = client.get('/admin/all-loans/', follow=False)
    print(f'Status: {response.status_code}')
    print(f'Content-Type: {response.get("Content-Type")}')
    print(f'Content-Length: {len(response.content)}')
    print(f'Has stream_attr: {hasattr(response, "streaming")}')
    if hasattr(response, 'streaming'):
        print(f'Streaming: {response.streaming}')
    print(f'Resolver match: {response.resolver_match if hasattr(response, "resolver_match") else "N/A"}')
    print(f'Template used: {response.templates if hasattr(response, "templates") else "N/A"}')
    if len(response.content) > 0:
        print(f'First 100 chars: {response.content[:100]}')
    else:
        print("Content is EMPTY")
except Exception as e:
    print(f'Exception: {e}')
    import traceback
    traceback.print_exc()
