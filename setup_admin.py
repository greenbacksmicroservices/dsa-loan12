#!/usr/bin/env python
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dsa_loan_management.settings')
django.setup()

from core.models import User

# Get or create admin user with known password
admin = User.objects.get_or_create(
    username='admin',
    defaults={
        'email': 'admindsa@gmail.com',
        'first_name': 'Admin',
        'last_name': 'User',
        'role': 'admin',
        'is_staff': True,
        'is_superuser': True,
    }
)[0]

# Set password and email
admin.email = 'admindsa@gmail.com'
admin.set_password('admin123')
admin.role = 'admin'
admin.is_staff = True
admin.is_superuser = True
admin.save()

print(f"✓ Admin user configured:")
print(f"  Username: {admin.username}")
print(f"  Email: {admin.email}")
print(f"  Role: {admin.role}")
print(f"  Password: admin123")

# Test SubAdmin
from django.test import Client
client = Client()
resp = client.get('/subadmin/test-dashboard/')
print(f"\n✓ SubAdmin Dashboard Status: {resp.status_code}")

print(f"\n✓ READY TO LOGIN:")
print(f"  Go to: http://localhost:8000/admin-login/")
print(f"  Username: admin")
print(f"  Password: admin123")
print(f"  Email: admindsa@gmail.com")
