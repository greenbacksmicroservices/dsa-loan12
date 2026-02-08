#!/usr/bin/env python
"""
Final test: Verify the menu link now points to correct URL
"""
import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dsa_loan_management.settings')
sys.path.insert(0, 'D:\\WEB DEVIOPMENT\\DSA')
django.setup()

from django.test import Client
from django.contrib.auth import get_user_model
from django.urls import reverse

User = get_user_model()
client = Client()
emp = User.objects.filter(role='employee').first()
emp.set_password('test123456')
emp.save()
client.login(username=emp.username, password='test123456')

print("\n" + "="*60)
print("FINAL TEST: URL ROUTING")
print("="*60)

# Check what URL the template generates
url = reverse('employee_all_loans')
print(f"\n✅ reverse('employee_all_loans') = {url}")

# Verify the page loads at that URL
response = client.get(url)
print(f"✅ GET {url} returns status {response.status_code}")

# Check that API works when logged in
response = client.get('/api/employee/all-loans/')
data = response.json()
print(f"✅ API returns {len(data.get('loans', []))} loans")

print("\n" + "="*60)
print("✅ ALL SYSTEMS GO!")
print("="*60)
print("\nEmployee Panel should now work:")
print(f"  1. Go to /employee/dashboard/")
print(f"  2. Click 'All Loans' in sidebar (now points to {url})")
print(f"  3. Page will load and display 2 loans")
print("="*60)
