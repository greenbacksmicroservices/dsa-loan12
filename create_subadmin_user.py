#!/usr/bin/env python
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dsa_loan_management.settings')
django.setup()

from core.models import User

# Create or get SubAdmin user
user, created = User.objects.get_or_create(
    username='subadmin01',
    defaults={
        'email': 'subadmin01@dsaloanmanagement.com',
        'role': 'subadmin',
        'first_name': 'Test',
        'last_name': 'SubAdmin',
        'is_active': True
    }
)

# Update password
user.set_password('subadmin@123')
user.role = 'subadmin'
user.is_active = True
user.save()

print(f"✅ SubAdmin User Setup Complete!")
print(f"   Username: {user.username}")
print(f"   Email: {user.email}")
print(f"   Role: {user.role}")
print(f"   Active: {user.is_active}")
print(f"   Status: {'Created' if created else 'Updated'}")
