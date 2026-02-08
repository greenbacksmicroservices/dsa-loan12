#!/usr/bin/env python
import os, sys, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dsa_loan_management.settings')
sys.path.insert(0, 'D:\\WEB DEVIOPMENT\\DSA')
django.setup()

from core import employee_views

print("\n" + "="*60)
print("CHECKING FUNCTIONS IN employee_views")
print("="*60)

functions = [name for name in dir(employee_views) if not name.startswith('_') and callable(getattr(employee_views, name))]

print(f"\nTotal functions: {len(functions)}")

# Check for employee_all_loans
if 'employee_all_loans' in functions:
    print("\n✅ employee_all_loans FOUND")
    func = getattr(employee_views, 'employee_all_loans')
    print(f"   Function: {func}")
else:
    print("\n❌ employee_all_loans NOT FOUND")

# Check for similar names
print("\nFunctions with 'all_loans' in name:")
for func in [f for f in functions if 'all_loans' in f]:
    print(f"  - {func}")

print("\nFunctions with 'employee' in name:")
for func in [f for f in functions if 'employee' in f][:10]:
    print(f"  - {func}")
