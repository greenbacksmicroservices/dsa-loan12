import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dsa_loan_management.settings')
import django
django.setup()

from django.test import Client

client = Client()
client.login(username='admin', password='admin123')
resp = client.get('/admin/all-loans/')

html = resp.content.decode()

# Check for key elements
print("Key Elements in HTML:")
print(f"  Raj Kumar: {'Raj Kumar' in html}")
print(f"  Amit Patel: {'Amit Patel' in html}")
print(f"  Filter buttons: {'status-btn' in html}")
print(f"  Loan rows: {'loan-row' in html}")
print(f"  Loan table: {'<table' in html}")
print(f"  Extends base: {'extends' in html.lower()}")

# Show first 2000 chars of body
import re
body_match = re.search(r'<tbody[^>]*>(.*?)</tbody>', html, re.DOTALL)
if body_match:
    print("\nTable body content (first 1000 chars):")
    print(body_match.group(1)[:1000])
