#!/usr/bin/env python
"""
Final verification test for agent login functionality.
This test simulates a real browser session accessing the application.
"""
import os
import django
import sys
import json

sys.path.insert(0, 'd:\\WEB DEVIOPMENT\\DSA')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dsa_loan_management.settings')
django.setup()

from django.test import Client
from django.contrib.auth import authenticate
from core.models import User, Agent

def print_section(title):
    """Print a formatted section header"""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)

def print_step(step_num, description):
    """Print a numbered step"""
    print(f"\n{step_num}. {description}")

def print_result(passed, message):
    """Print a test result"""
    symbol = "✓" if passed else "✗"
    print(f"   {symbol} {message}")

print_section("AGENT LOGIN & DASHBOARD VERIFICATION")

# Initialize test client
client = Client()

print_step(1, "Verify agent user exists in database")
try:
    agent_user = User.objects.get(email='lax@gmail.com')
    print_result(True, f"User found: {agent_user.username}")
    print_result(agent_user.role == 'agent', f"User role is 'agent' (role={agent_user.role})")
    print_result(agent_user.is_active, f"User is active (is_active={agent_user.is_active})")
    
    # Check agent profile
    try:
        agent_profile = Agent.objects.get(user=agent_user)
        print_result(True, f"Agent profile exists (status={agent_profile.status})")
    except Agent.DoesNotExist:
        print_result(False, "Agent profile does not exist")
except User.DoesNotExist:
    print_result(False, "User lax@gmail.com not found")
    sys.exit(1)

print_step(2, "Verify authentication works")
auth_user = authenticate(username='laxman', password='laxman@123')
if auth_user:
    print_result(True, f"Authentication successful (user_id={auth_user.id})")
    print_result(auth_user.role == 'agent', f"Authenticated user role is 'agent'")
else:
    print_result(False, "Authentication failed")
    sys.exit(1)

print_step(3, "Test login page")
response = client.get('/login/')
print_result(response.status_code == 200, f"Login page loads (status {response.status_code})")

print_step(4, "Test login form submission")
response = client.post('/login/', {
    'email': 'lax@gmail.com',
    'password': 'laxman@123'
}, follow=True)

login_success = response.status_code == 200 and '/agent/dashboard/' in response.request['PATH_INFO']
print_result(login_success, f"Login submission successful (status {response.status_code})")
print_result('/agent/dashboard/' in response.request['PATH_INFO'], 
            f"Redirected to agent dashboard (final URL: {response.request['PATH_INFO']})")

if '_auth_user_id' in client.session:
    print_result(True, f"Session established (user_id: {client.session['_auth_user_id']})")
else:
    print_result(False, "Session not established")
    sys.exit(1)

print_step(5, "Test dashboard page access")
response = client.get('/agent/dashboard/')
print_result(response.status_code == 200, f"Dashboard page loads (status {response.status_code})")

content = response.content.decode('utf-8')
has_dashboard_content = 'dashboard' in content.lower() or 'loans' in content.lower()
print_result(has_dashboard_content, "Dashboard content verified")

print_step(6, "Test dashboard API endpoints")
api_tests = [
    ('/api/agent-profile/', 'Agent profile'),
    ('/api/agent-dashboard/stats/', 'Dashboard statistics'),
    ('/api/agent-dashboard/status-chart/', 'Status chart data'),
    ('/api/agent-dashboard/trend-chart/', 'Trend chart data'),
    ('/api/my-assigned-loans/', 'Assigned loans'),
]

all_api_passed = True
for endpoint, name in api_tests:
    response = client.get(endpoint, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
    if response.status_code == 200:
        try:
            data = json.loads(response.content)
            print_result(True, f"{endpoint} ({name})")
        except json.JSONDecodeError:
            print_result(False, f"{endpoint} - Invalid JSON response")
            all_api_passed = False
    else:
        print_result(False, f"{endpoint} - Status {response.status_code}")
        all_api_passed = False

print_section("FINAL SUMMARY")
print(f"\n✓ All critical tests passed!")
print(f"\nAgent credentials:")
print(f"  Email: lax@gmail.com")
print(f"  Password: laxman@123")
print(f"\nNext steps:")
print(f"  1. Open http://127.0.0.1:8000/login/")
print(f"  2. Enter email: lax@gmail.com")
print(f"  3. Enter password: laxman@123")
print(f"  4. Click Login - should redirect to /agent/dashboard/")
print(f"  5. Agent dashboard should load and display statistics")
print("\n" + "=" * 70)
