#!/usr/bin/env python
import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dsa_loan_management.settings')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

django.setup()

from core.models import Complaint, User, Agent

print(f"Total complaints: {Complaint.objects.count()}")
print(f"Total employees (role=employee): {User.objects.filter(role='employee').count()}")
print(f"Total agents: {Agent.objects.count()}")

# Check first few complaints
for c in Complaint.objects.all()[:5]:
    print(f"  - Complaint ID: {c.complaint_id}, Type: {c.complaint_type}, Status: {c.status}")
