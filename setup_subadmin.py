#!/usr/bin/env python
import os
import django
import sys

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dsa_loan_management.settings')
django.setup()

from core.models import User
from django.contrib.auth.hashers import make_password

# Delete existing subadmin if exists
User.objects.filter(username='subadmin01').delete()

# Create SubAdmin user
subadmin = User.objects.create(
    username='subadmin01',
    email='subadmin01@dsaloanmanagement.com',
    password=make_password('subadmin@123'),
    first_name='SubAdmin',
    last_name='Panel',
    role='subadmin',
    phone='+923001234567',
    is_active=True,
    is_staff=False,
    is_superuser=False
)

print("\n" + "="*70)
print("✅ SubAdmin User Created Successfully!")
print("="*70)
print(f"\n📋 LOGIN CREDENTIALS:")
print(f"   Username: subadmin01")
print(f"   Password: subadmin@123")
print(f"   Email: subadmin01@dsaloanmanagement.com")
print(f"   Role: SubAdmin")
print(f"\n🔗 ACCESS URL: http://localhost:8000/subadmin/dashboard/")
print(f"\n📌 SubAdmin Panel Navigation:")
print(f"   • Dashboard - Overview & Statistics")
print(f"   • All Loans - View all loan applications")
print(f"   • My Agent - Manage assigned agents/staff")
print(f"   • My Employee - Manage assigned employees")
print(f"   • Reports - View analytics and reports")
print(f"   • Settings - Account settings and preferences")
print(f"\n⚠️  IMPORTANT: Save these credentials securely!")
print("="*70 + "\n")
