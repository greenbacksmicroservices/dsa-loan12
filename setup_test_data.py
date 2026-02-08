#!/usr/bin/env python
"""
Simple setup script to create test users for admin dashboard
"""
import os
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dsa_loan_management.settings')
django.setup()

from django.contrib.auth import get_user_model

User = get_user_model()

print("\n" + "="*60)
print("SETTING UP TEST DATA FOR ADMIN DASHBOARD")
print("="*60)

# Create admin user if not exists
admin_user, created = User.objects.get_or_create(
    username='admin',
    defaults={
        'email': 'admin@dsa.com',
        'first_name': 'Admin',
        'last_name': 'User',
        'role': 'admin',
        'is_active': True
    }
)
if created:
    admin_user.set_password('admin123')
    admin_user.save()
    print("[OK] Created admin user")
else:
    admin_user.set_password('admin123')
    admin_user.save()
    print("[OK] Admin user exists - password updated")

# Create employees
print("\n1. Creating employees...")
for i in range(3):
    emp, created = User.objects.get_or_create(
        username=f'employee{i+1}',
        defaults={
            'email': f'employee{i+1}@dsa.com',
            'first_name': f'Employee',
            'last_name': f'{i+1}',
            'role': 'employee',
            'is_active': True
        }
    )
    emp.set_password('password123')
    emp.save()
    print(f"  [OK] {emp.first_name} {emp.last_name} ({emp.email})")

# Create agents
print("\n2. Creating agents...")
for i in range(3):
    agent, created = User.objects.get_or_create(
        username=f'agent{i+1}',
        defaults={
            'email': f'agent{i+1}@dsa.com',
            'first_name': f'Agent',
            'last_name': f'{i+1}',
            'role': 'agent',
            'is_active': True
        }
    )
    agent.set_password('password123')
    agent.save()
    print(f"  [OK] {agent.first_name} {agent.last_name} ({agent.email})")

print("\n" + "="*60)
print("[SUCCESS] TEST DATA SETUP COMPLETE")
print("="*60)
print("\nDashboard URL: http://127.0.0.1:8000/admin-dashboard/")
print("Admin Login: admin / admin123")
print("\nNote: Employee and Agent lists will display in the dashboard")
print("when you refresh the page after logging in.\n")
