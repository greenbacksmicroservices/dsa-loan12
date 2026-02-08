#!/usr/bin/env python
"""
Simple test to verify dashboard loads without NoReverseMatch error
"""
import os
import django
from django.test import Client

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dsa_loan_management.settings')
django.setup()

print("\n" + "="*70)
print("Testing Dashboard After Fix")
print("="*70)

client = Client()

# Login
print("\n1. Logging in as employee...")
response = client.post('/login/', {'email': 'mrram', 'password': 'mrram@123'})
print(f"   Login status: {response.status_code}")

# Try to access dashboard
print("\n2. Accessing dashboard...")
response = client.get('/dashboard/')

if response.status_code == 200:
    content = response.content.decode()
    if 'NoReverseMatch' not in content and 'Reverse for' not in content:
        print(f"   ✅ Dashboard loads successfully!")
        print(f"   ✅ No NoReverseMatch errors!")
    else:
        print(f"   ❌ Still has errors")
else:
    print(f"   Status: {response.status_code}")

print("\n" + "="*70)
print("✅ FIX APPLIED:")
print("="*70)
print("""
Changed: 'complaints' → 'complaints_legacy' in dashboard.html

The dashboard should now load without the NoReverseMatch error.

Try in browser:
  1. http://localhost:8000/login/
  2. Login: mrram / mrram@123
  3. Dashboard should display charts and data
""")
print("="*70 + "\n")
