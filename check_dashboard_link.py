import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dsa_loan_management.settings')
import django
django.setup()

from django.test import Client
import re

client = Client()
client.login(username='admin', password='admin123')
resp = client.get('/admin/all-loans/')

html = resp.content.decode()

# Look for dashboard link
matches = re.findall(r'href=["\']([^"\']*dashboard[^"\']*)["\']', html, re.IGNORECASE)
if matches:
    print('Found Dashboard links:')
    for m in matches:
        print(f'  {m}')
else:
    print('Dashboard link NOT found')

# Check total length and key marker
print(f'\nHTML size: {len(html)} bytes')
print(f'Has admin_dashboard URL: {"admin_dashboard" in html}')
print(f'Has Dashboard text: {"Dashboard" in html}')
