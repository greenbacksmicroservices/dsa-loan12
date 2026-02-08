#!/usr/bin/env python
"""
Create test data - assign loans to employees
"""
import os
import django
from datetime import timedelta

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dsa_loan_management.settings')
django.setup()

from django.utils import timezone
from core.models import Loan, User, ActivityLog

print("=" * 80)
print("CREATING TEST DATA - ASSIGNING LOANS TO EMPLOYEES")
print("=" * 80)

# Get first employee
employees = User.objects.filter(role='employee').order_by('id')
admin = User.objects.filter(role='admin').first()

if not employees.exists():
    print("❌ No employees found!")
    exit(1)

# Get unassigned loans
unassigned_loans = Loan.objects.filter(assigned_employee__isnull=True)[:8]

if not unassigned_loans.exists():
    print("❌ No unassigned loans found!")
    exit(1)

print(f"\nFound {unassigned_loans.count()} unassigned loans")
print(f"Found {employees.count()} employees")

# Assign loans alternately to employees
for idx, loan in enumerate(unassigned_loans):
    employee = employees[idx % len(employees)]
    old_status = loan.status
    
    # Assign the loan
    loan.assigned_employee = employee
    loan.assigned_at = timezone.now() - timedelta(hours=idx+2)  # Stagger by hours for testing
    loan.status = 'waiting'  # Change status to waiting
    loan.save()
    
    # Log the activity
    ActivityLog.objects.create(
        user=admin,
        action=f"Assigned loan to {employee.username}",
        description=f"Admin assigned loan #{loan.id} ({loan.full_name}) to employee {employee.username}"
    )
    
    print(f"✓ Loan #{loan.id} ({loan.full_name}) -> {employee.username} (status: {old_status} -> {loan.status})")

print("\n" + "=" * 80)
print("TEST DATA CREATED - Loans assigned to employees!")
print("=" * 80)

# Verify assignment
print("\nVerification:")
for emp in employees[:3]:
    count = Loan.objects.filter(assigned_employee=emp).count()
    waiting = Loan.objects.filter(assigned_employee=emp, status__in=['waiting', 'follow_up']).count()
    print(f"  {emp.username}: {count} total, {waiting} waiting/follow_up")
