#!/usr/bin/env python
"""
Get admin email and password info
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dsa_loan_management.settings')
django.setup()

from core.models import User
from django.contrib.auth import authenticate

print("\n" + "="*70)
print("🔑 ADMIN USER DETAILS")
print("="*70)

# Get all admin users
admins = User.objects.filter(role='admin')

print(f"\nTotal Admin Users: {admins.count()}\n")

for admin in admins:
    print(f"Username: {admin.username}")
    print(f"Email: {admin.email}")
    print(f"Role: {admin.role}")
    print(f"Is Active: {admin.is_active}")
    print("-" * 70)

print("\n" + "="*70)
print("🧪 TESTING ADMIN LOGIN WITH DIFFERENT PASSWORDS")
print("="*70)

# Test with different password combinations
test_passwords = [
    'admin123',
    'admin@123',
    'admin',
    'Admin@123',
    'adminadmin',
]

admin_user = User.objects.filter(role='admin', username='admin').first()

if admin_user:
    print(f"\nTesting user: {admin_user.username} ({admin_user.email})")
    print("-" * 70)
    
    for pwd in test_passwords:
        user = authenticate(username=admin_user.username, password=pwd)
        if user:
            print(f"✅ Password '{pwd}' works!")
        else:
            print(f"❌ Password '{pwd}' does NOT work")
else:
    print("No admin user found with username 'admin'")

print("\n" + "="*70)
print("💡 LOGIN INSTRUCTIONS:")
print("="*70)
print("""
Go to: http://localhost:8000/admin-login/

Enter:
  Email/Username: admin
  Password: [one of the passwords above marked with ✅]

Then click "Log in"
""")
print("="*70 + "\n")
