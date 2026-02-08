#!/usr/bin/env python
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dsa_loan_management.settings')

import django
django.setup()

from django.test import Client
from core.models import User

admin = User.objects.filter(username='admin').first()
if admin:
    admin.set_password('admin123')
    admin.save()

client = Client()
client.login(username='admin', password='admin123')

resp_page = client.get('/admin/all-loans/')
resp_api = client.get('/api/admin-all-loans/')

print('All Loans Page:', resp_page.status_code)
print('API Endpoint:', resp_api.status_code)

if resp_api.status_code == 200:
    print('✓ FIXED')
else:
    print('ERROR')
