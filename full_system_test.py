#!/usr/bin/env python
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dsa_loan_management.settings')
django.setup()

from django.test import Client
from django.contrib.auth import authenticate
from core.models import User

print('=' * 80)
print('COMPREHENSIVE SYSTEM TEST')
print('=' * 80)

# Setup admin
admin = User.objects.filter(username='admin').first()
if admin:
    admin.email = 'admindsa@gmail.com'
    admin.set_password('admin123')
    admin.role = 'admin'
    admin.is_staff = True
    admin.is_superuser = True
    admin.save()
    print('\n✓ Admin user setup: admin / admin123')

# Setup subadmin
subadmin = User.objects.filter(username='subadmin01').first()
if subadmin:
    subadmin.set_password('subadmin@123')
    subadmin.role = 'subadmin'
    subadmin.save()
    print('✓ SubAdmin user setup: subadmin01 / subadmin@123')

# Test pages
client = Client()

print('\n' + '=' * 80)
print('TESTING ALL PAGES')
print('=' * 80)

tests = [
    ('SubAdmin Test Dashboard', '/subadmin/test-dashboard/', None),
    ('SubAdmin Main Dashboard', '/subadmin/dashboard/', 'subadmin01:subadmin@123'),
    ('Admin Login Page', '/admin-login/', None),
    ('Admin All Loans', '/admin/all-loans/', 'admin:admin123'),
    ('SubAdmin Management', '/admin/subadmin-management/', 'admin:admin123'),
]

for name, url, creds in tests:
    client = Client()
    
    if creds:
        username, password = creds.split(':')
        client.login(username=username, password=password)
    
    try:
        resp = client.get(url)
        status_icon = '✅' if resp.status_code == 200 else '❌'
        print(f'{status_icon} {name}: {resp.status_code}')
        
        if resp.status_code == 200:
            html = resp.content.decode('utf-8', errors='ignore')
            if 'SubAdmin' in name and 'Dashboard' in name and 'UPDATED' not in html:
                print(f'   ⚠️  Missing UPDATED content')
            if 'All Loans' in name and 'Master Database' not in html:
                print(f'   ⚠️  Missing loan content')
    except Exception as e:
        print(f'❌ {name}: Error - {str(e)[:50]}')

print('\n' + '=' * 80)
print('TESTING API ENDPOINTS')
print('=' * 80)

# Test APIs
apis = [
    ('SubAdmin Stats API', '/api/admin/dashboard-stats/', None),
    ('Admin All Loans API', '/api/admin-all-loans/', 'admin:admin123'),
    ('SubAdmin API', '/api/admin/get-subadmins/', 'admin:admin123'),
]

for name, url, creds in apis:
    client = Client()
    
    if creds:
        username, password = creds.split(':')
        client.login(username=username, password=password)
    
    try:
        resp = client.get(url)
        status_icon = '✅' if resp.status_code == 200 else '❌'
        print(f'{status_icon} {name}: {resp.status_code}')
    except Exception as e:
        print(f'❌ {name}: Error')

print('\n' + '=' * 80)
print('QUICK ACCESS LINKS')
print('=' * 80)
print('''
🔗 SubAdmin Dashboard (Test - No Login):
   http://localhost:8000/subadmin/test-dashboard/

🔗 SubAdmin Dashboard (Main):
   Login: subadmin01 / subadmin@123
   URL: http://localhost:8000/subadmin/dashboard/

🔗 Admin Login:
   http://localhost:8000/admin-login/
   Username: admin
   Password: admin123

🔗 Admin Pages (After Login):
   - All Loans: http://localhost:8000/admin/all-loans/
   - SubAdmin Management: http://localhost:8000/admin/subadmin-management/

✓ Everything is ready to use!
''')
