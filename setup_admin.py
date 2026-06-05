#!/usr/bin/env python
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dsa_loan_management.settings')
django.setup()

from core.models import User

ADMIN_USERNAME = 'admin'
ADMIN_EMAIL = 'admin@gmail.com'
ADMIN_PASSWORD = '123456789'

# Get or create admin user with known password.
admin = User.objects.get_or_create(
    username=ADMIN_USERNAME,
    defaults={
        'email': ADMIN_EMAIL,
        'first_name': 'Admin',
        'last_name': 'User',
        'role': 'admin',
        'is_staff': True,
        'is_superuser': True,
        'is_active': True,
    },
)[0]

# Keep the admin account aligned with the shared app login.
admin.email = ADMIN_EMAIL
admin.set_password(ADMIN_PASSWORD)
admin.role = 'admin'
admin.is_staff = True
admin.is_superuser = True
admin.is_active = True
admin.save()

print("Admin user configured:")
print(f"  Username: {admin.username}")
print(f"  Email: {admin.email}")
print(f"  Role: {admin.role}")
print(f"  Password: {ADMIN_PASSWORD}")

from django.test import Client

client = Client()
resp = client.get('/subadmin/test-dashboard/')
print(f"\nSubAdmin Dashboard Status: {resp.status_code}")

print("\nREADY TO LOGIN:")
print("  Go to: http://localhost:8000/admin-login/")
print(f"  Username: {ADMIN_USERNAME}")
print(f"  Password: {ADMIN_PASSWORD}")
print(f"  Email: {ADMIN_EMAIL}")
