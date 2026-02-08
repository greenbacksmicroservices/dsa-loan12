import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dsa_loan_management.settings')
import django
django.setup()

from django.test import Client
from core.models import User, Loan

print("=" * 60)
print("ALL LOANS PAGE TEST")
print("=" * 60)

# Setup admin user
admin_user = User.objects.filter(username='admin').first()
if not admin_user:
    admin_user = User.objects.create_superuser('admin', 'admin@test.com', 'admin123')
    print("Created admin user")
else:
    admin_user.set_password('admin123')
    admin_user.save()
    print("Updated admin password")

# Create test loans with unique user_id
import uuid

test_loans = [
    {'full_name': 'Raj Kumar', 'mobile_number': '9876543210', 'email': 'raj@example.com', 'loan_amount': 500000, 'status': 'new_entry', 'loan_type': 'personal', 'user_id': f'USER{uuid.uuid4().hex[:8].upper()}'},
    {'full_name': 'Priya Singh', 'mobile_number': '9876543211', 'email': 'priya@example.com', 'loan_amount': 750000, 'status': 'approved', 'loan_type': 'home', 'user_id': f'USER{uuid.uuid4().hex[:8].upper()}'},
    {'full_name': 'Amit Patel', 'mobile_number': '9876543212', 'email': 'amit@example.com', 'loan_amount': 300000, 'status': 'waiting', 'loan_type': 'business', 'user_id': f'USER{uuid.uuid4().hex[:8].upper()}'}
]

for loan_data in test_loans:
    if not Loan.objects.filter(mobile_number=loan_data['mobile_number']).exists():
        Loan.objects.create(**loan_data)
        print(f"Created loan for {loan_data['full_name']}")

print("\n✓ Test Data Setup Complete")
print("-" * 60)

# Test page access
client = Client()
login_ok = client.login(username='admin', password='admin123')
print(f"\n✓ Login successful: {login_ok}")

resp = client.get('/admin/all-loans/')
print(f"✓ Page Status: {resp.status_code}")

if resp.status_code == 200:
    html = resp.content.decode()
    print(f"✓ Page size: {len(html)} bytes")
    
    # Check key elements
    checks = {
        'All Loans heading': 'All Loans' in html,
        'Filter buttons': 'status-btn' in html,
        'Loan table rows': 'loan-row' in html,
        'Applicant names': 'Raj Kumar' in html or 'applicant_name' in html,
        'Extends admin_base': 'admin_base' in html or 'sidebar' in html.lower(),
        'Status filter options': 'new_entry' in html or 'NEW' in html,
    }
    
    print("\n✓ Page Elements Check:")
    all_ok = True
    for check_name, result in checks.items():
        status = "✓" if result else "✗"
        print(f"  {status} {check_name}")
        if not result:
            all_ok = False
    
    if all_ok:
        print("\n" + "=" * 60)
        print("✓✓✓ ALL LOANS PAGE IS WORKING CORRECTLY! ✓✓✓")
        print("=" * 60)
    else:
        print("\n⚠ Some checks failed")
else:
    print(f"✗ Error: HTTP {resp.status_code}")
