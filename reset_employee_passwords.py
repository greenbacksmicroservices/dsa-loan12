#!/usr/bin/env python
import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dsa_loan_management.settings')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

django.setup()

from core.models import User

print("=" * 80)
print("EMPLOYEE PASSWORD RESET - Setting Default Passwords")
print("=" * 80)

# Get all employees
employees = User.objects.filter(role='employee')

print(f"\nFound {employees.count()} employees\n")

for emp in employees:
    # Set password to username@123
    default_password = f"{emp.username}@123"
    emp.set_password(default_password)
    emp.save()
    
    print(f"✅ {emp.username}")
    print(f"   Password set to: {default_password}")
    print(f"   Email: {emp.email}")
    print()

print("=" * 80)
print("ALL EMPLOYEE PASSWORDS RESET")
print("=" * 80)

print("\n📝 New Employee Login Credentials:")
print("\nUsername | Password")
print("---------|----------")
for emp in employees:
    print(f"{emp.username} | {emp.username}@123")
