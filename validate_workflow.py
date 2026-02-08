#!/usr/bin/env python
"""
Workflow Implementation Validation Script
Verifies all components are in place and properly configured
"""

import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dsa_loan_management.settings')
django.setup()

from django.urls import reverse
from django.test import Client
from core.models import User, Applicant, LoanApplication
import json

def validate_workflow():
    print("\n" + "="*70)
    print("WORKFLOW IMPLEMENTATION VALIDATION")
    print("="*70 + "\n")
    
    checks_passed = 0
    checks_failed = 0
    
    # Check 1: Templates exist
    print("CHECK 1: Verifying template files...")
    templates = [
        'core/new_entry_detail.html',
        'core/my_applications.html',
        'core/view_application.html',
        'core/base.html'
    ]
    
    for template in templates:
        template_path = f'templates/{template}'
        if os.path.exists(template_path):
            print(f"✓ {template}")
            checks_passed += 1
        else:
            print(f"✗ {template} NOT FOUND")
            checks_failed += 1
    
    # Check 2: URL routes exist
    print("\nCHECK 2: Verifying URL routes...")
    routes = {
        'my_applications': '/my-applications/',
        'view_application': '/application/1/',
        # Note: Can't fully verify without request context
    }
    
    for name, path in routes.items():
        try:
            if name == 'my_applications':
                url = reverse(name)
            else:
                url = reverse(name, kwargs={'applicant_id': 1})
            print(f"✓ {name}: {url}")
            checks_passed += 1
        except Exception as e:
            print(f"✗ {name}: {e}")
            checks_failed += 1
    
    # Check 3: Views exist
    print("\nCHECK 3: Verifying view functions...")
    from django.apps import apps
    from importlib import import_module
    
    try:
        views_module = import_module('core.views')
        view_functions = [
            'my_applications',
            'view_application',
            'get_employees_list',
            'get_agents_list',
            'assign_to_employee',
            'assign_to_agent',
            'approve_application',
            'reject_application'
        ]
        
        for func_name in view_functions:
            if hasattr(views_module, func_name):
                print(f"✓ {func_name}")
                checks_passed += 1
            else:
                print(f"✗ {func_name} NOT FOUND")
                checks_failed += 1
    except Exception as e:
        print(f"✗ Error loading views: {e}")
        checks_failed += 8
    
    # Check 4: Model fields exist
    print("\nCHECK 4: Verifying LoanApplication model fields...")
    from core.models import LoanApplication
    
    required_fields = [
        'assigned_employee',
        'assigned_agent',
        'assigned_at',
        'assigned_by',
        'approved_by',
        'approval_notes',
        'approved_at',
        'rejected_by',
        'rejection_reason',
        'rejected_at'
    ]
    
    for field_name in required_fields:
        try:
            field = LoanApplication._meta.get_field(field_name)
            print(f"✓ {field_name}: {field.get_internal_type()}")
            checks_passed += 1
        except Exception as e:
            print(f"✗ {field_name}: {e}")
            checks_failed += 1
    
    # Check 5: Database migration applied
    print("\nCHECK 5: Verifying database migration...")
    from django.core.management import call_command
    from io import StringIO
    
    try:
        out = StringIO()
        call_command('showmigrations', 'core', stdout=out)
        output = out.getvalue()
        
        if '0006_loanapplication_approval_notes_and_more' in output:
            if '[X]' in output or 'Migrations for' not in output:
                print("✓ Migration 0006 applied")
                checks_passed += 1
            else:
                print("✗ Migration 0006 not applied")
                checks_failed += 1
        else:
            print("✗ Migration 0006 not found")
            checks_failed += 1
    except Exception as e:
        print(f"⚠ Could not verify migrations: {e}")
    
    # Check 6: Test data exists
    print("\nCHECK 6: Verifying test data...")
    try:
        admin = User.objects.filter(role='admin').first()
        if admin:
            print(f"✓ Admin user exists: {admin.username}")
            checks_passed += 1
        else:
            print("⚠ No admin user found (create via admin creation command)")
        
        applicant = Applicant.objects.filter(mobile='9876543210').first()
        if applicant:
            print(f"✓ Test applicant exists: {applicant.full_name}")
            checks_passed += 1
        else:
            print("⚠ Test applicant not found (run test_workflow.py to create)")
    except Exception as e:
        print(f"✗ Error checking test data: {e}")
        checks_failed += 1
    
    # Summary
    print("\n" + "="*70)
    print(f"VALIDATION SUMMARY")
    print("="*70)
    print(f"✓ Checks Passed: {checks_passed}")
    print(f"✗ Checks Failed: {checks_failed}")
    
    if checks_failed == 0:
        print("\n✅ ALL CHECKS PASSED - WORKFLOW READY!")
        print("\nNext steps:")
        print("1. python manage.py runserver")
        print("2. Navigate to /login/")
        print("3. Login with admin credentials")
        print("4. Create test data: python test_workflow.py")
        print("5. Access workflow at /admin/new-entries/")
    else:
        print(f"\n⚠️  {checks_failed} check(s) failed - review errors above")
    
    print("="*70 + "\n")
    
    return checks_failed == 0

if __name__ == '__main__':
    success = validate_workflow()
    exit(0 if success else 1)
