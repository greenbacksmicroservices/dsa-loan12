#!/usr/bin/env python
import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dsa_loan_management.settings')
django.setup()

from django.test import Client
from django.contrib.auth import get_user_model

User = get_user_model()

client = Client()

# Try to get an existing subadmin user
user = User.objects.filter(role='subadmin').first()
if not user:
    print("ERROR: No subadmin user found")
    sys.exit(1)

# Try different password combinations
passwords_to_try = ['password123', 'subadmin123', 'test123', 'admin123']
login_success = False
for pwd in passwords_to_try:
    login_success = client.login(username=user.email, password=pwd)
    if login_success:
        print(f"Login successful with: {user.email}")
        break

if not login_success:
    print(f"WARNING: Could not login with {user.email}. Using force_login instead.")
    client.force_login(user)
print(f'Login: {"Success" if login_success else "Failed"}')

test_urls = [
    '/subadmin/dashboard/',
    '/subadmin/my-employees/',
    '/subadmin/my-agents/',
    '/subadmin/all-loans/',
    '/subadmin/complaints/',
    '/subadmin/reports/',
]

print('=' * 60)
print('TESTING SUBADMIN PAGES FOR ANNOTATION CONFLICTS')
print('=' * 60)

for url in test_urls:
    try:
        response = client.get(url)
        status = 'OK' if response.status_code == 200 else f'ERROR {response.status_code}'
        print(f'{url}: {status}')
        if response.status_code != 200:
            content = response.content.decode()
            if 'ValueError' in content and 'annotation' in content:
                print(f'   ANNOTATION CONFLICT FOUND')
            if 'FieldError' in content:
                print(f'   FIELD ERROR FOUND')
    except Exception as e:
        err_msg = str(e)
        print(f'{url}: EXCEPTION - {err_msg[:100]}')

print('=' * 60)
