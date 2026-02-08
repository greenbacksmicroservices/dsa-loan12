#!/usr/bin/env python
"""
Get all login credentials - Email and Password
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dsa_loan_management.settings')
django.setup()

from core.models import User

print("\n" + "="*80)
print("📋 COMPLETE LOGIN CREDENTIALS - EMAIL & PASSWORD")
print("="*80)

print("\n" + "👥 EMPLOYEES ".ljust(80, "="))
print("\nURL: http://localhost:8000/login/\n")

employees = User.objects.filter(role='employee').order_by('username')
for emp in employees:
    print(f"Email/Username: {emp.username:20} | Email: {emp.email:30} | Password: {emp.username}@123")

print("\n" + "💼 AGENTS ".ljust(80, "="))
print("\nURL: http://localhost:8000/login/\n")

agents = User.objects.filter(role='agent').order_by('username')
for agent in agents:
    email = agent.email if agent.email else "(no email)"
    if agent.username == 'testagent1':
        pwd = 'test.agent@123'
    else:
        pwd = f'{agent.username}@123'
    print(f"Email/Username: {agent.username:20} | Email: {email:30} | Password: {pwd}")

print("\n" + "🔑 ADMIN ".ljust(80, "="))
print("\nURL: http://localhost:8000/admin-login/\n")

admins = User.objects.filter(role='admin').order_by('username')
for admin in admins:
    if admin.username == 'admin':
        pwd = 'admin123'
    else:
        pwd = 'testadmin@123'
    print(f"Email/Username: {admin.username:20} | Email: {admin.email:30} | Password: {pwd}")

print("\n" + "="*80)
print("✅ HOW TO LOGIN:")
print("="*80)
print("""
STEP 1: Make sure server is running
  - Open terminal
  - Run: python manage.py runserver
  - Wait for: "Starting development server at http://127.0.0.1:8000/"

STEP 2: Clear browser cache
  - Press: Ctrl + Shift + Delete
  - Select: "All time"
  - Check: "Cookies" and "Cached images"
  - Click: "Clear data"

STEP 3: LOGIN AS EMPLOYEE
  - Go to: http://localhost:8000/login/
  - Enter Email/Username: mrram
  - Enter Password: mrram@123
  - Click: "Log in"

STEP 4: You should see Employee Dashboard ✅

If you want to try Agent:
  - Same URL: http://localhost:8000/login/
  - Enter: laxman / laxman@123

If you want to try Admin:
  - Go to: http://localhost:8000/admin-login/
  - Enter: admin / admin123
""")
print("="*80 + "\n")
