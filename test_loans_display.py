#!/usr/bin/env python
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dsa_loan_management.settings')
django.setup()

from core.models import Loan
from datetime import datetime
from dateutil.relativedelta import relativedelta

loans = Loan.objects.all()[:3]
print(f"Total loans in DB: {Loan.objects.count()}\n")

for loan in loans:
    loan_end_date = loan.created_at + relativedelta(months=loan.tenure_months) if loan.tenure_months else None
    print(f"Loan ID: {loan.user_id}")
    print(f"  Borrower: {loan.full_name}")
    print(f"  Type: {loan.get_loan_type_display()}")
    print(f"  Amount: ₹{loan.loan_amount}")
    print(f"  Interest Rate: {loan.interest_rate}%")
    print(f"  Tenure: {loan.tenure_months} months")
    print(f"  EMI: ₹{loan.emi}")
    print(f"  Start Date: {loan.created_at.date()}")
    print(f"  End Date: {loan_end_date.date() if loan_end_date else 'N/A'}")
    print(f"  Status: {loan.get_status_display()}")
    print()
