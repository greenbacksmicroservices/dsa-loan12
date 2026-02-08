#!/usr/bin/env python
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dsa_loan_management.settings')
import django
django.setup()

from core.models import User

# Delete all existing users
User.objects.all().delete()
print("✓ All users deleted\n")

# Create Admin User
admin_user = User.objects.create_user(
    username='admin',
    email='admin@dsaloan.com',
    password='Admin@123456',
    first_name='Admin',
    last_name='User',
    role='admin',
    is_staff=True,
    is_superuser=True,
    is_active=True
)

# Create Employee User
employee_user = User.objects.create_user(
    username='employee1',
    email='employee1@dsaloan.com',
    password='Employee@123456',
    first_name='John',
    last_name='Doe',
    role='employee',
    is_active=True
)

# Create DSA User
dsa_user = User.objects.create_user(
    username='dsa1',
    email='dsa1@dsaloan.com',
    password='DSA@123456',
    first_name='DSA',
    last_name='Manager',
    role='dsa',
    is_active=True
)

# Create Agent User
agent_user = User.objects.create_user(
    username='agent1',
    email='agent1@dsaloan.com',
    password='Agent@123456',
    first_name='Rajesh',
    last_name='Agent',
    role='agent',
    is_active=True
)

print("="*70)
print("🎉 NEW USER CREDENTIALS CREATED SUCCESSFULLY!")
print("="*70)
print("\n📌 ADMIN USER:")
print("   Username: admin")
print("   Email: admin@dsaloan.com")
print("   Password: Admin@123456")
print("   Role: Admin (Full Access)")

print("\n📌 EMPLOYEE USER:")
print("   Username: employee1")
print("   Email: employee1@dsaloan.com")
print("   Password: Employee@123456")
print("   Role: Employee")

print("\n📌 DSA USER:")
print("   Username: dsa1")
print("   Email: dsa1@dsaloan.com")
print("   Password: DSA@123456")
print("   Role: DSA Manager")

print("\n📌 AGENT USER:")
print("   Username: agent1")
print("   Email: agent1@dsaloan.com")
print("   Password: Agent@123456")
print("   Role: Agent")

print("\n" + "="*70)
print("✓ Total users created: 4")
print("="*70)
print("\n🔗 Login URL: http://127.0.0.1:8000/login/")
print("🔗 Admin Login URL: http://127.0.0.1:8000/admin-login/")
