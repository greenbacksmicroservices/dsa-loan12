#!/usr/bin/env python
"""
Check what the API is actually returning in detail
"""
import os
import sys
import django
import json

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dsa_loan_management.settings')
sys.path.insert(0, 'D:\\WEB DEVIOPMENT\\DSA')
django.setup()

from django.test import Client
from django.contrib.auth import get_user_model

User = get_user_model()

client = Client()
employee = User.objects.filter(role='employee').first()

# Set password and login
employee.set_password('test123456')
employee.save()
client.login(username=employee.username, password='test123456')

# Get API response
response = client.get('/api/employee/all-loans/')
data = response.json()

print("\n" + "="*60)
print("FULL API RESPONSE")
print("="*60)
print(json.dumps(data, indent=2, default=str))

print("\n" + "="*60)
print("LOAN DATA FIELDS")
print("="*60)

if data.get('loans'):
    loan = data['loans'][0]
    print(f"Available fields in first loan:")
    for key in sorted(loan.keys()):
        print(f"  - {key}: {loan[key]}")
else:
    print("No loans returned")
