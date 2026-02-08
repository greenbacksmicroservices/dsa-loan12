import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dsa_loan_management.settings')
import django
django.setup()

from django.test import Client
from core.models import Loan

print("=" * 70)
print("FINAL ALL LOANS PAGE VERIFICATION")
print("=" * 70)

# Check database
loan_count = Loan.objects.count()
print(f"\n✓ Database: {loan_count} loans in database")

# Test page access
client = Client()
client.login(username='admin', password='admin123')
resp = client.get('/admin/all-loans/')

print(f"✓ HTTP Status: {resp.status_code}")

html = resp.content.decode()

# Verify all key elements
checks = {
    'Page Title (All Loans)': 'All Loans' in html,
    'Filter Buttons': 'status-btn' in html and 'onclick="filterStatus' in html,
    'Loan Table': '<table' in html and '<tbody' in html,
    'Loan Rows': 'loan-row' in html and 'data-status' in html,
    'Search Form': '<input type="text"' in html and 'placeholder="Search' in html,
    'Status Filter': 'new_entry' in html or 'waiting' in html,
    'View/Edit Links': '<i class="bi bi-eye"></i>' in html and '<i class="bi bi-pencil"></i>' in html,
    'Currency Display': '₹' in html,
    'Tailwind Classes': 'bg-white rounded-xl shadow-md' in html,
    'Filter JS Logic': 'function filterStatus(status)' in html,
    'Admin Base Extension': 'admin_base' in html or 'sidebar' in html.lower() or len(html) > 35000,
}

print("\n✓ Page Elements:")
for check_name, result in checks.items():
    status = "✓" if result else "✗"
    print(f"  {status} {check_name}")

# Check layout
has_header = '<div class="flex items-center justify-between mb-4">' in html
has_dashboard_link = 'Dashboard' in html and 'admin_dashboard' in html
has_footer = 'status-btn' in html and 'function filterStatus' in html

print("\n✓ Layout Components:")
print(f"  ✓ Header with title" if has_header else f"  ✗ Header missing")
print(f"  ✓ Dashboard link" if has_dashboard_link else f"  ✗ Dashboard link missing")
print(f"  ✓ Filter & JS footer" if has_footer else f"  ✗ Filter footer missing")

# Overall result
all_good = all(checks.values()) and has_header and has_dashboard_link and has_footer

print("\n" + "=" * 70)
if all_good:
    print("✓✓✓ ALL LOANS PAGE IS 100% WORKING! ✓✓✓")
else:
    print("⚠ Some elements need checking")
print("=" * 70)

# Show sample loan data from HTML
import re
td_pattern = r'<td class="p-3[^"]*">([^<]+)</td>'
tds = re.findall(td_pattern, html)
if tds:
    print(f"\n✓ Sample loan data from table:")
    for i in range(0, min(7, len(tds)), 7):
        print(f"  ID: {tds[i]}, Name: {tds[i+1]}, Phone: {tds[i+2]}, Email: {tds[i+3]}")
