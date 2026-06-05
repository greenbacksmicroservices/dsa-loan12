#!/usr/bin/env python
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dsa_loan_management.settings')
django.setup()

from core.models import User

ADMIN_USERNAME = 'admin'
ADMIN_EMAIL = 'admin@gmail.com'
ADMIN_PASSWORD = '123456789'

user, created = User.objects.get_or_create(
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
)

user.email = ADMIN_EMAIL
user.role = 'admin'
user.is_staff = True
user.is_superuser = True
user.is_active = True
user.set_password(ADMIN_PASSWORD)
user.save()

action = 'created' if created else 'updated'
print(f"Admin user {action} successfully!")
print(f"  Username: {user.username}")
print(f"  Email: {user.email}")
print(f"  Password: {ADMIN_PASSWORD}")
