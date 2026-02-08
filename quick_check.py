#!/usr/bin/env python
"""
Quick check - are the APIs responding?
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dsa_loan_management.settings')
django.setup()

from django.contrib.auth import get_user_model
from core.models import Loan, ActivityLog

User = get_user_model()

# Get employee details
employee = User.objects.filter(role='employee').first()

if employee:
    print(f"Employee: {employee.username}")
    print(f"Email: {employee.email}")
    print(f"Password: (not shown)")
    
    # Check loans
    loans = Loan.objects.filter(assigned_employee=employee)
    print(f"\nAssigned Loans: {loans.count()}")
    
    for loan in loans[:3]:
        print(f"  - ID:{loan.id}, Name:{loan.full_name}, Status:{loan.status}, Hours:{loan.get_hours_since_assignment()}h")
    
    # Get admin for assignment test
    admin = User.objects.filter(role='admin').first()
    print(f"\nAdmin: {admin.username}")
    print(f"Admin Email: {admin.email}")
    
    # Get unassigned loans for assignment test
    unassigned = Loan.objects.filter(assigned_employee__isnull=True).first()
    if unassigned:
        print(f"\nUnassigned Loan Available: ID={unassigned.id}, Name={unassigned.full_name}")
else:
    print("No employee found!")
