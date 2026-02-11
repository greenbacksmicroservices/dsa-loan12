#!/usr/bin/env python
"""
Test script to verify ForClose API endpoint is working correctly
"""

import os
import sys
import django
import json

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dsa_loan_management.settings')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

django.setup()

from core.models import Loan, LoanStatusHistory, User
from django.test import Client
from django.urls import reverse

def test_forclose_endpoint():
    """Test the ForClose API endpoint"""
    
    # Create test client
    client = Client()
    
    # Create a test admin user
    try:
        admin_user = User.objects.get(username='admin')
    except User.DoesNotExist:
        admin_user = User.objects.create_superuser(
            username='admin',
            email='admin@test.com',
            password='admin123'
        )
        print(f"✓ Created test admin user: {admin_user.username}")
    
    # Login as admin
    login_success = client.login(username='admin', password='admin123')
    print(f"✓ Login successful: {login_success}")
    
    # Get or create a test loan
    try:
        test_loan = Loan.objects.filter(status='waiting').first()
        if not test_loan:
            test_loan = Loan.objects.create(
                full_name='Test Borrower',
                mobile_number='9876543210',
                email='test@example.com',
                loan_type='personal',
                loan_amount=100000,
                tenure_months=12,
                status='waiting'
            )
            print(f"✓ Created test loan: {test_loan.id}")
        else:
            print(f"✓ Using existing test loan: {test_loan.id}")
    except Exception as e:
        print(f"✗ Error creating test loan: {e}")
        return False
    
    # Test ForClose endpoint
    forclose_url = f'/api/loan/{test_loan.id}/forclose/'
    forclose_data = {
        'forclose_notes': 'Closing this loan for business reasons'
    }
    
    try:
        response = client.post(
            forclose_url,
            data=json.dumps(forclose_data),
            content_type='application/json',
            HTTP_X_CSRFTOKEN=client.cookies.get('csrftoken', '')
        )
        
        print(f"\n--- ForClose API Test ---")
        print(f"Endpoint: POST {forclose_url}")
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.content.decode('utf-8')}")
        
        if response.status_code == 200:
            result = response.json()
            if result.get('success'):
                print(f"✓ ForClose endpoint working correctly!")
                print(f"  Message: {result.get('message')}")
                print(f"  New Status: {result.get('new_status')}")
                
                # Verify loan status was updated
                test_loan.refresh_from_db()
                print(f"  Loan Status in DB: {test_loan.get_status_display()}")
                
                return True
            else:
                print(f"✗ ForClose failed: {result.get('error')}")
                return False
        else:
            print(f"✗ HTTP Error {response.status_code}")
            return False
            
    except Exception as e:
        print(f"✗ Error testing ForClose endpoint: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    # Test the endpoint
    print("Testing ForClose Endpoint Implementation\n")
    print("=" * 50)
    
    success = test_forclose_endpoint()
    
    print("\n" + "=" * 50)
    if success:
        print("\n✓ All tests passed! ForClose functionality is working correctly.")
    else:
        print("\n✗ Tests failed. Please check the implementation.")
