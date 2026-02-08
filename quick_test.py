import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dsa_loan_management.settings')
import django
django.setup()

from django.test import Client
from django.contrib.auth import get_user_model

User = get_user_model()

client = Client()
user = User.objects.get(email='agent1@dsaloan.com')
client.force_login(user)

print("\n" + "="*70)
print(" AGENT DASHBOARD - VERIFICATION")
print("="*70)

# Test 1: Dashboard loads
response = client.get('/agent/dashboard/')
print(f"\n[TEST 1] Dashboard Load: {response.status_code}")
if response.status_code == 200:
    content = response.content.decode()
    items = {
        "Header dropdown": "userMenuBtn" in content,
        "My Profile": "My Profile" in content,
        "Change Password": "Change Password" in content,
        "Logout": "/logout/" in content,
        "Stat cards": "total-assigned" in content,
        "Charts": "loanStatusChart" in content,
        "My Loans table": "My Assigned Loans" in content,
        "Sidebar": "sidebar-menu" in content,
        "Agent menu items": "My Loans" in content,
        "No admin items": "new_entries" not in content,
        "Auto-refresh": "30000" in content,
    }
    for item, check in items.items():
        print(f"  {'PASS' if check else 'FAIL'}: {item}")

# Test 2: API status
print(f"\n[TEST 2] API Status")
api_response = client.get('/api/my-assigned-loans/')
print(f"  /api/my-assigned-loans/: {api_response.status_code}")

print("\n" + "="*70)
print("COMPLETE")
print("="*70 + "\n")
