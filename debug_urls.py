#!/usr/bin/env python
import os, sys, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dsa_loan_management.settings')
sys.path.insert(0, 'D:\\WEB DEVIOPMENT\\DSA')
django.setup()

print("\n" + "="*60)
print("DEBUG: Checking URL Patterns")
print("="*60)

# Import raw URLs from core.urls
from core.urls import urlpatterns

# Find all admin and subadmin patterns
print(f"\nTotal URL patterns in core.urls.urlpatterns: {len(urlpatterns)}")
print("\nAll 'admin' and 'subadmin' patterns:")
for i, pattern in enumerate(urlpatterns):
    pattern_str = str(pattern.pattern)
    if 'admin' in pattern_str.lower():
        name = pattern.name if hasattr(pattern, 'name') else '(no name)'
        print(f"  [{i}]: {pattern_str:40} → {name}")

print("\n" + "="*60)
