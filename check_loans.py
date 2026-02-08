#!/usr/bin/env python
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dsa_loan_management.settings')
django.setup()

from core.models import Loan
from django.db.models import Count

print(f'Total Loans: {Loan.objects.count()}')
print('\nLoans by Status:')
status_count = Loan.objects.values('status').annotate(count=Count('id'))
for item in status_count:
    print(f"  {item['status']}: {item['count']}")
