#!/usr/bin/env python
"""
FINAL VERIFICATION - Employee Panel Working Status
Run this to verify all systems are operational
"""
import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dsa_loan_management.settings')
django.setup()

from django.urls import reverse
from django.contrib.auth import get_user_model
from core.models import Loan

User = get_user_model()

print("\n" + "="*80)
print("✅ EMPLOYEE PANEL - FINAL VERIFICATION")
print("="*80)

all_pass = True

# CHECK 1: URLs are registered
print("\n[1] Checking URL endpoints...")
try:
    reverse('api_employee_all_loans')
    print("    ✅ /api/employee/all-loans/ registered")
except:
    print("    ❌ /api/employee/all-loans/ NOT registered")
    all_pass = False

try:
    reverse('api_employee_new_entry_requests')
    print("    ✅ /api/employee/new-entry-requests/ registered")
except:
    print("    ❌ /api/employee/new-entry-requests/ NOT registered")
    all_pass = False

try:
    reverse('api_admin_assign_loan')
    print("    ✅ /api/admin/assign-loan/ registered")
except:
    print("    ❌ /api/admin/assign-loan/ NOT registered")
    all_pass = False

# CHECK 2: Employees exist
print("\n[2] Checking employee accounts...")
employees = User.objects.filter(role='employee')
print(f"    ✅ {employees.count()} employee(s) found")
if employees.count() == 0:
    print("    ❌ No employees found!")
    all_pass = False

# CHECK 3: Test data exists
print("\n[3] Checking test data...")
total_loans = Loan.objects.count()
assigned_loans = Loan.objects.filter(assigned_employee__isnull=False).count()
waiting_loans = Loan.objects.filter(status__in=['waiting', 'follow_up']).count()

print(f"    ✅ Total loans: {total_loans}")
print(f"    ✅ Assigned loans: {assigned_loans}")
print(f"    ✅ Waiting/Follow-up loans: {waiting_loans}")

if assigned_loans == 0:
    print("    ⚠️  WARNING: No loans assigned to employees!")
    print("         Run: python create_test_loans_for_employee.py")

# CHECK 4: Employee can see their loans
print("\n[4] Checking employee data access...")
for emp in employees[:2]:
    emp_loans = Loan.objects.filter(assigned_employee=emp)
    print(f"    ✅ {emp.username}: {emp_loans.count()} loan(s)")

# CHECK 5: Model methods
print("\n[5] Checking model methods...")
sample_loan = Loan.objects.filter(assigned_employee__isnull=False).first()
if sample_loan:
    hours = sample_loan.get_hours_since_assignment()
    print(f"    ✅ Hours pending calculation: {hours}h")
else:
    print("    ⚠️  No assigned loans to check calculation")

# CHECK 6: API endpoints
print("\n[6] Checking API responses...")

from rest_framework.test import APIRequestFactory
from core.employee_views_new import employee_all_loans_api, employee_new_entry_requests_api

factory = APIRequestFactory()

if employees.exists():
    emp = employees.first()
    
    # Test All Loans API
    try:
        request = factory.get('/api/employee/all-loans/')
        request.user = emp
        response = employee_all_loans_api(request)
        if response.status_code == 200:
            data = response.data
            print(f"    ✅ All Loans API: {len(data.get('loans', []))} loans returned")
        else:
            print(f"    ❌ All Loans API: Status {response.status_code}")
            all_pass = False
    except Exception as e:
        print(f"    ❌ All Loans API: Error - {str(e)}")
        all_pass = False
    
    # Test New Entry Requests API
    try:
        request = factory.get('/api/employee/new-entry-requests/')
        request.user = emp
        response = employee_new_entry_requests_api(request)
        if response.status_code == 200:
            data = response.data
            print(f"    ✅ New Entry Requests API: {len(data.get('loans', []))} requests returned")
        else:
            print(f"    ❌ New Entry Requests API: Status {response.status_code}")
            all_pass = False
    except Exception as e:
        print(f"    ❌ New Entry Requests API: Error - {str(e)}")
        all_pass = False

# SUMMARY
print("\n" + "="*80)
if all_pass:
    print("✅ ALL CHECKS PASSED - SYSTEM READY")
    print("="*80)
    print("\nEmployee Panel Status: ✅ WORKING")
    print("\nNext Steps:")
    print("  1. Start server: python manage.py runserver 0.0.0.0:8000")
    print("  2. Login as: laxmi (or any employee)")
    print("  3. Click 'All Loans' in sidebar")
    print("  4. Verify data loads correctly")
    sys.exit(0)
else:
    print("❌ SOME CHECKS FAILED")
    print("="*80)
    print("\nPlease fix the issues above before deployment.")
    sys.exit(1)
