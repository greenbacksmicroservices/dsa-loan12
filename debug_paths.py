#!/usr/bin/env python
import os, sys, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dsa_loan_management.settings')
sys.path.insert(0, 'D:\\WEB DEVIOPMENT\\DSA')
django.setup()

from django.urls import path
from core import subadmin_views

print("Testing path() creation...\n")

# Test the two missing paths
try:
    p1 = path('subadmin/dashboard/', subadmin_views.subadmin_dashboard, name='subadmin_dashboard')
    print(f"✓ path1 created: {p1}")
    print(f"  - Pattern: {p1.pattern}")
    print(f"  - Name: {p1.name}")
    print(f"  - Callable: {p1.callback}")
except Exception as e:
    print(f"✗ path1 FAILED: {type(e).__name__}: {e}")

try:
    p2 = path('api/subadmin/dashboard-stats/', subadmin_views.api_subadmin_dashboard_stats, name='api_subadmin_dashboard_stats')
    print(f"\n✓ path2 created: {p2}")
    print(f"  - Pattern: {p2.pattern}")
    print(f"  - Name: {p2.name}")
    print(f"  - Callable: {p2.callback}")
except Exception as e:
    print(f"\n✗ path2 FAILED: {type(e).__name__}: {e}")

# Now test if they appear in the list
print("\n\nNow checking if they appear in urlpatterns...")
from core.urls import urlpatterns

dashboard_found = any('subadmin/dashboard/' == str(p.pattern) for p in urlpatterns)
stats_found = any('api/subadmin/dashboard-stats/' == str(p.pattern) for p in urlpatterns)

print(f"subadmin/dashboard/ in urlpatterns: {dashboard_found}")
print(f"api/subadmin/dashboard-stats/ in urlpatterns: {stats_found}")
