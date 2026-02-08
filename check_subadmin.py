#!/usr/bin/env python
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dsa_loan_management.settings')
django.setup()

from core.models import User

u = User.objects.filter(email='subadmin01@dsaloanmanagement.com').first()
if u:
    print(f"✓ SubAdmin User Found!")
    print(f"  Username: {u.username}")
    print(f"  Email: {u.email}")
    print(f"  Role: {u.role}")
    print(f"  Active: {u.is_active}")
else:
    print("✗ SubAdmin user NOT found. Creating it...")
    u = User.objects.create_user(
        username='subadmin01',
        email='subadmin01@dsaloanmanagement.com',
        password='subadmin@123',
        role='subadmin',
        is_active=True
    )
    print(f"✓ SubAdmin user created successfully!")
    print(f"  Username: {u.username}")
    print(f"  Email: {u.email}")
    print(f"  Role: {u.role}")
