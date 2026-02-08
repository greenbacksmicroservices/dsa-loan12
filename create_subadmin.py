#!/usr/bin/env python
"""
Script to create a SubAdmin user for testing
Run: python manage.py shell < create_subadmin.py
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dsa_loan_management.settings')
django.setup()

from core.models import User

# Delete existing subadmin if exists
User.objects.filter(username='subadmin01').delete()

# Create SubAdmin user
subadmin = User.objects.create_user(
    username='subadmin01',
    email='subadmin01@dsaloanmanagement.com',
    password='subadmin@123',
    first_name='SubAdmin',
    last_name='Panel',
    role='subadmin',
    phone='+923001234567',
    is_active=True
)

print("\n" + "="*60)
print("✅ SubAdmin User Created Successfully!")
print("="*60)
print(f"\n📋 Login Credentials:")
print(f"   Username: subadmin01")
print(f"   Password: subadmin@123")
print(f"   Email: subadmin01@dsaloanmanagement.com")
print(f"   Role: SubAdmin")
print(f"\n🔗 Access URL: http://localhost:8000/subadmin/dashboard/")
print(f"\n⚠️  IMPORTANT: Save these credentials securely!")
print("="*60 + "\n")
