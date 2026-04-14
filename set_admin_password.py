#!/usr/bin/env python
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dsa_loan_management.settings')
django.setup()

from core.models import User

email = 'admin@gmail.com'
password = '123456789'

try:
    # Try to get existing admin user
    user = User.objects.get(username='admin')
    user.email = email
    user.set_password(password)
    user.save()
    print(f"✓ Admin password updated successfully!")
    print(f"  Username: admin")
    print(f"  Email: {email}")
    print(f"  Password: {password}")
except User.DoesNotExist:
    # Create new admin user
    user = User.objects.create_superuser('admin', email, password)
    print(f"✓ Admin user created successfully!")
    print(f"  Username: admin")
    print(f"  Email: {email}")
    print(f"  Password: {password}")
