#!/usr/bin/env python
"""
Setup test employee and agent accounts
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dsa_loan_management.settings')
django.setup()

from core.models import User, Agent

def setup_accounts():
    """Create or update employee and agent test accounts"""
    
    print("🔧 Setting up test accounts...")
    
    # ==================== EMPLOYEE ACCOUNT ====================
    print("\n📋 Employee Account:")
    emp_email = "emp12@gmail.com"
    emp_password = "123456789"
    
    try:
        # Check if employee exists
        emp_user = User.objects.filter(email=emp_email).first()
        
        if emp_user:
            # Update password
            emp_user.set_password(emp_password)
            emp_user.save()
            print(f"   ✅ Updated existing employee: {emp_email}")
        else:
            # Create new employee
            emp_user = User.objects.create_user(
                username=emp_email.split('@')[0],  # emp12
                email=emp_email,
                password=emp_password,
                role='employee',
                first_name='Employee',
                last_name='Test',
                is_active=True
            )
            print(f"   ✅ Created new employee: {emp_email}")
            
        print(f"   └─ ID: {emp_user.id}")
        print(f"   └─ Username: {emp_user.username}")
        print(f"   └─ Role: {emp_user.role}")
        print(f"   └─ Active: {emp_user.is_active}")
        
    except Exception as e:
        print(f"   ❌ Error with employee: {str(e)}")
    
    # ==================== AGENT ACCOUNT ====================
    print("\n🎯 Agent Account:")
    agent_email = "agent12@gmail.com"
    agent_password = "123456789"
    
    try:
        # Check if agent user exists
        agent_user = User.objects.filter(email=agent_email).first()
        
        if agent_user:
            # Update password
            agent_user.set_password(agent_password)
            agent_user.save()
            print(f"   ✅ Updated existing agent user: {agent_email}")
        else:
            # Create new agent user
            agent_user = User.objects.create_user(
                username=agent_email.split('@')[0],  # agent12
                email=agent_email,
                password=agent_password,
                role='agent',
                first_name='Agent',
                last_name='Test',
                is_active=True
            )
            print(f"   ✅ Created new agent user: {agent_email}")
            
        print(f"   └─ ID: {agent_user.id}")
        print(f"   └─ Username: {agent_user.username}")
        print(f"   └─ Role: {agent_user.role}")
        print(f"   └─ Active: {agent_user.is_active}")
        
        # Check if Agent profile exists
        agent_profile = Agent.objects.filter(user=agent_user).first()
        
        if not agent_profile:
            agent_profile = Agent.objects.create(
                user=agent_user,
                agent_id=f"AGENT_{agent_user.id}",
                name="Agent Test",
                phone="9999999999",
                email=agent_email,
                status='active'
            )
            print(f"   ✅ Created agent profile: {agent_profile.agent_id}")
        else:
            print(f"   ✅ Agent profile exists: {agent_profile.agent_id}")
        
    except Exception as e:
        print(f"   ❌ Error with agent: {str(e)}")
    
    print("\n" + "="*60)
    print("✨ Account Setup Complete!")
    print("="*60)
    print("\n📝 Test Credentials:")
    print(f"\n🔐 Employee:")
    print(f"   Email: emp12@gmail.com")
    print(f"   Password: 123456789")
    print(f"   Login URL: http://localhost:8000/login/")
    print(f"\n🔐 Agent:")
    print(f"   Email: agent12@gmail.com")
    print(f"   Password: 123456789")
    print(f"   Login URL: http://localhost:8000/login/")

if __name__ == '__main__':
    setup_accounts()
