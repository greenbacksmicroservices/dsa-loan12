"""
Verification Script for Employee Panel Implementation
Run this to verify all components are properly set up
"""

import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dsa_loan_management.settings')
django.setup()

from core.models import User, Loan, Agent, ActivityLog
from django.utils import timezone

def check_files_exist():
    """Check if all required files are in place"""
    print("\n" + "="*60)
    print("FILE VERIFICATION")
    print("="*60)
    
    files_to_check = [
        ('core/employee_views_new.py', 'Employee Views (NEW)'),
        ('core/admin_assign_views.py', 'Admin Assignment Views (NEW)'),
        ('templates/core/employee/all_loans_new.html', 'All Loans Template (NEW)'),
        ('templates/core/employee/new_entry_request_new.html', 'New Entry Template (NEW)'),
        ('templates/core/employee/loan_detail_new.html', 'Loan Detail Template (NEW)'),
        ('templates/core/employee/my_agents_new.html', 'My Agents Template (NEW)'),
    ]
    
    for filepath, description in files_to_check:
        full_path = os.path.join(os.path.dirname(__file__), filepath)
        if os.path.exists(full_path):
            print(f"✓ {description}: EXISTS")
        else:
            print(f"✗ {description}: MISSING - {filepath}")
    
    return

def check_database_fields():
    """Check if Loan model has required fields"""
    print("\n" + "="*60)
    print("DATABASE FIELD VERIFICATION")
    print("="*60)
    
    required_fields = [
        ('assigned_employee', 'ForeignKey to User'),
        ('assigned_at', 'DateTimeField'),
        ('status', 'CharField'),
        ('action_taken_at', 'DateTimeField'),
    ]
    
    for field_name, field_type in required_fields:
        try:
            field = Loan._meta.get_field(field_name)
            print(f"✓ Loan.{field_name}: EXISTS ({field.__class__.__name__})")
        except:
            print(f"✗ Loan.{field_name}: MISSING - {field_type}")

def check_status_choices():
    """Check if status choices are defined"""
    print("\n" + "="*60)
    print("STATUS CHOICES VERIFICATION")
    print("="*60)
    
    expected_statuses = [
        'new_entry',
        'waiting',
        'follow_up',
        'approved',
        'rejected',
        'disbursed'
    ]
    
    status_field = Loan._meta.get_field('status')
    available_statuses = [choice[0] for choice in status_field.choices]
    
    for status in expected_statuses:
        if status in available_statuses:
            print(f"✓ Status '{status}': AVAILABLE")
        else:
            print(f"✗ Status '{status}': MISSING")

def check_test_data():
    """Create and verify test data"""
    print("\n" + "="*60)
    print("TEST DATA VERIFICATION")
    print("="*60)
    
    # Check or create test admin
    admin, created = User.objects.get_or_create(
        username='test_admin',
        defaults={
            'role': 'admin',
            'email': 'admin@test.com',
            'first_name': 'Test',
            'last_name': 'Admin'
        }
    )
    if created:
        admin.set_password('admin123')
        admin.save()
        print(f"✓ Test Admin created: {admin.username}")
    else:
        print(f"✓ Test Admin exists: {admin.username}")
    
    # Check or create test employee
    emp, created = User.objects.get_or_create(
        username='test_emp1',
        defaults={
            'role': 'employee',
            'email': 'emp@test.com',
            'first_name': 'Employee',
            'last_name': 'One'
        }
    )
    if created:
        emp.set_password('emp123')
        emp.save()
        print(f"✓ Test Employee created: {emp.username}")
    else:
        print(f"✓ Test Employee exists: {emp.username}")
    
    # Check or create test agent
    agent, created = Agent.objects.get_or_create(
        name='Test Agent',
        defaults={
            'phone': '9876543210',
            'email': 'agent@test.com',
            'created_by': admin
        }
    )
    if created:
        print(f"✓ Test Agent created: {agent.name}")
    else:
        print(f"✓ Test Agent exists: {agent.name}")
    
    # Check or create test loan
    loan, created = Loan.objects.get_or_create(
        full_name='Test Applicant',
        mobile_number='9123456789',
        defaults={
            'email': 'applicant@test.com',
            'loan_type': 'personal',
            'loan_amount': 500000,
            'assigned_agent': agent,
            'created_by': admin,
            'status': 'new_entry'
        }
    )
    if created:
        print(f"✓ Test Loan created: {loan.full_name}")
    else:
        print(f"✓ Test Loan exists: {loan.full_name}")

def verify_assignment_workflow():
    """Verify the assignment workflow"""
    print("\n" + "="*60)
    print("ASSIGNMENT WORKFLOW VERIFICATION")
    print("="*60)
    
    try:
        # Get test data
        admin = User.objects.get(username='test_admin')
        emp = User.objects.get(username='test_emp1')
        
        # Get a new_entry loan
        loan = Loan.objects.filter(status='new_entry').first()
        
        if not loan:
            print("✗ No NEW_ENTRY loans found for testing")
            return
        
        print(f"Testing assignment with:")
        print(f"  - Loan: {loan.full_name}")
        print(f"  - Employee: {emp.get_full_name()}")
        
        # Perform assignment (simulating admin action)
        loan.assigned_employee = emp
        loan.assigned_at = timezone.now()
        loan.status = 'waiting'
        loan.save()
        
        print("✓ Assignment performed successfully")
        
        # Verify assignment
        loan.refresh_from_db()
        print(f"✓ Loan status changed: {loan.status}")
        print(f"✓ Assigned to: {loan.assigned_employee.get_full_name()}")
        print(f"✓ Assigned at: {loan.assigned_at}")
        
        # Verify visibility in employee view
        emp_loans = Loan.objects.filter(assigned_employee=emp)
        if loan in emp_loans:
            print(f"✓ Loan visible in employee view: YES")
        else:
            print(f"✗ Loan visible in employee view: NO")
        
        # Verify visibility in new entry requests
        new_entry_loans = Loan.objects.filter(
            assigned_employee=emp,
            status__in=['waiting', 'follow_up']
        )
        if loan in new_entry_loans:
            print(f"✓ Loan visible in 'New Entry Requests': YES")
        else:
            print(f"✗ Loan visible in 'New Entry Requests': NO")
        
        # Test approval action
        loan.status = 'approved'
        loan.action_taken_at = timezone.now()
        loan.save()
        
        loan.refresh_from_db()
        print(f"✓ Approval action successful")
        print(f"  - New status: {loan.status}")
        print(f"  - Action taken at: {loan.action_taken_at}")
        
    except Exception as e:
        print(f"✗ Error in workflow: {str(e)}")

def verify_agent_creation():
    """Verify agent creation by employee"""
    print("\n" + "="*60)
    print("AGENT CREATION VERIFICATION")
    print("="*60)
    
    try:
        emp = User.objects.get(username='test_emp1')
        
        # Check agents created by this employee
        emp_agents = Agent.objects.filter(created_by=emp)
        print(f"✓ Agents created by {emp.get_full_name()}: {emp_agents.count()}")
        
        for agent in emp_agents:
            print(f"  - {agent.name} ({agent.email})")
            print(f"    Status: {agent.status}")
            print(f"    Created: {agent.created_at}")
        
        # Verify creation marker
        for agent in emp_agents:
            creation_source = 'Employee-Created' if agent.created_by.role == 'employee' else 'Admin-Created'
            print(f"  ✓ {agent.name}: {creation_source}")
        
    except Exception as e:
        print(f"✗ Error checking agents: {str(e)}")

def verify_activity_logging():
    """Verify activity logging"""
    print("\n" + "="*60)
    print("ACTIVITY LOGGING VERIFICATION")
    print("="*60)
    
    try:
        logs = ActivityLog.objects.all().order_by('-created_at')[:10]
        
        if logs.count() == 0:
            print("✓ No activity logs yet (expected for fresh install)")
        else:
            print(f"✓ Recent activity logs: {logs.count()}")
            for log in logs:
                print(f"  - {log.get_action_display()}: {log.description}")
                print(f"    By: {log.user.get_full_name() if log.user else 'System'}")
                print(f"    At: {log.created_at}")
    
    except Exception as e:
        print(f"✗ Error checking logs: {str(e)}")

def generate_report():
    """Generate comprehensive verification report"""
    print("\n" + "="*60)
    print("EMPLOYEE PANEL IMPLEMENTATION VERIFICATION REPORT")
    print("="*60 + "\n")
    
    # Run all checks
    check_files_exist()
    check_database_fields()
    check_status_choices()
    check_test_data()
    verify_assignment_workflow()
    verify_agent_creation()
    verify_activity_logging()
    
    # Summary
    print("\n" + "="*60)
    print("VERIFICATION COMPLETE")
    print("="*60)
    print("\nNext steps:")
    print("1. Review all checks above")
    print("2. Address any ✗ (failed) checks")
    print("3. Test in browser:")
    print("   - Admin: http://localhost:8000/admin-login/")
    print("   - Username: test_admin")
    print("   - Password: admin123")
    print("4. Assign test loan to test_emp1")
    print("5. Login as employee: http://localhost:8000/login/")
    print("   - Username: test_emp1")
    print("   - Password: emp123")
    print("6. Verify loan appears in 'New Entry Requests'")
    print("7. Test Approve/Reject/Disburse actions")
    print("\n✓ Implementation ready for testing!")

if __name__ == '__main__':
    generate_report()
