#!/usr/bin/env python
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dsa_loan_management.settings')
django.setup()

from core.models import Loan, Agent, User
from datetime import datetime, timedelta
import time
import uuid

# Get or create an agent
agent = Agent.objects.first() or Agent.objects.create(
    name="Test Agent",
    phone="9876543210",
    email="agent@test.com"
)

# Create or get employee
employee = User.objects.filter(role='employee').first()
if not employee:
    employee = User.objects.create_user(
        username='testemployee2',
        email='testemployee2@test.com',
        password='test123',
        role='employee',
        first_name='Test',
        last_name='Employee'
    )

# Clear old test loans (keep the original 2)
# Loan.objects.filter(applicant_name__startswith='Test').delete()

# Create test loans with different statuses
test_data = [
    ('waiting', 'Ram Singh'),
    ('follow_up', 'Priya Sharma'),
    ('approved', 'Amit Kumar'),
    ('approved', 'Deepika Verma'),
    ('rejected', 'Rajesh Patel'),
    ('disbursed', 'Anisha Khan'),
    ('disbursed', 'Vikas Desai'),
]

for status, name in test_data:
    time.sleep(0.1)  # Small delay to avoid timestamp collision
    loan = Loan.objects.create(
        full_name=name,
        mobile_number='9876543210',
        email=f'{name.lower().replace(" ", "")}@test.com',
        loan_amount=50000,
        status=status,
        loan_type='personal',
        user_id=f"USR{uuid.uuid4().hex[:12].upper()}",  # Use unique ID instead of timestamp
        assigned_agent=agent,
        created_by=employee,
    )
    print(f"Created loan: {name} - Status: {status}")

# Show summary
from django.db.models import Count
print("\n\nLoan Status Summary:")
print("-" * 40)
summary = Loan.objects.values('status').annotate(count=Count('id')).order_by('status')
for item in summary:
    print(f"  {item['status'].upper():20} : {item['count']:3}")

print(f"\nTotal loans: {Loan.objects.count()}")
