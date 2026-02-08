#!/usr/bin/env python
"""
Detailed diagnostic script to show exactly what's happening with login
"""
import os
import django
from django.test import Client
import urllib.parse

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dsa_loan_management.settings')
django.setup()

print("\n" + "="*80)
print("🔧 DETAILED LOGIN DIAGNOSTIC TEST")
print("="*80)

client = Client()

# Test the login form submission step by step
print("\n📝 STEP 1: Access the login page")
print("-" * 80)
response = client.get('/login/')
print(f"✅ Status: {response.status_code}")
print(f"✅ URL: /login/")

# Check if there are any messages from previous requests
print(f"✅ Messages in response: {list(response.context.get('messages', []) if response.context else [])}")

print("\n📝 STEP 2: Submit credentials via POST")
print("-" * 80)

# Try with the exact form fields from login.html
test_cases = [
    ('mrram', 'mrram@123', 'Employee mrram'),
    ('cee', 'cee@123', 'Employee cee'),
    ('laxman', 'laxman@123', 'Agent laxman'),
]

for username, password, label in test_cases:
    print(f"\n  Testing: {label}")
    print(f"    Username: {username}")
    print(f"    Password: {password}")
    
    # Submit form with email field (as per login.html)
    response = client.post('/login/', {
        'email': username,
        'password': password
    })
    
    print(f"    ↳ Response Status: {response.status_code}")
    
    if response.status_code == 302:
        redirect_url = response.url
        print(f"    ↳ Redirect to: {redirect_url}")
        if 'dashboard' in redirect_url:
            print(f"    ↳ ✅ SUCCESS - Redirects to dashboard!")
        else:
            print(f"    ↳ ❌ Unexpected redirect")
    elif response.status_code == 200:
        print(f"    ↳ ❌ FAILED - Page reloaded (authentication failed)")
        # Check what error message appears
        content_str = response.content.decode()
        if 'Invalid email or password' in content_str:
            print(f"    ↳ Error: Invalid email or password")
        elif 'Unauthorized access' in content_str:
            print(f"    ↳ ERROR: Showing admin error message!")
            print(f"    ↳ This means form posted to /admin-login/ instead of /login/")
    else:
        print(f"    ↳ Unexpected status code: {response.status_code}")

print("\n" + "="*80)
print("🎯 WHAT TO DO NEXT:")
print("="*80)
print("""
If you see "✅ SUCCESS - Redirects to dashboard!" above:
  → The login system is WORKING CORRECTLY!
  → Try these steps in your browser:
    1. Go to: http://localhost:8000/login/
    2. Enter: mrram (email field) and mrram@123 (password)
    3. Click Login
    4. You should see the employee dashboard
    
If you STILL see the "Unauthorized" error in browser:
  1. Clear browser cache (Ctrl+Shift+Delete)
  2. Close the browser completely
  3. Restart the Django server: python manage.py runserver
  4. Try again at http://localhost:8000/login/

If authentication still fails:
  1. Check you're entering credentials correctly
  2. Try: laxman / laxman@123 (agent account)
  3. Contact support if error persists
""")
print("="*80 + "\n")
