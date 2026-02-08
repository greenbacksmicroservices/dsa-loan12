#!/usr/bin/env python
"""
Check if the employee_all_loans URL pattern is registered
"""
import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dsa_loan_management.settings')
sys.path.insert(0, 'D:\\WEB DEVIOPMENT\\DSA')
django.setup()

from django.urls import get_resolver, reverse

print("\n" + "="*60)
print("CHECKING URL PATTERNS")
print("="*60)

resolver = get_resolver()

# Get all URL patterns
patterns = resolver.url_patterns

print(f"\nTotal URL patterns: {len(patterns)}")

# Search for employee_all_loans
found = False
for pattern in patterns:
    if hasattr(pattern, 'name') and pattern.name == 'employee_all_loans':
        print(f"\n✅ Found 'employee_all_loans' pattern!")
        print(f"   Pattern: {pattern.pattern}")
        print(f"   View: {pattern.callback}")
        found = True
        
        # Try to reverse it
        try:
            url = reverse('employee_all_loans')
            print(f"   Reversed URL: {url}")
        except Exception as e:
            print(f"   Error reversing: {e}")
        break

if not found:
    print("\n❌ 'employee_all_loans' pattern NOT FOUND")
    print("\nAvailable patterns:")
    for pattern in patterns:
        if hasattr(pattern, 'name'):
            print(f"  - {pattern.name}")

print("\n" + "="*60)
