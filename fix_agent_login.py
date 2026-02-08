#!/usr/bin/env python
import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dsa_loan_management.settings')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

django.setup()

from core.models import User, Agent
from django.utils.text import slugify

print("=" * 80)
print("FIXING AGENT LOGIN - CREATING USER ACCOUNTS")
print("=" * 80)

agents = Agent.objects.filter(user__isnull=True)

print(f"\nFound {agents.count()} agents without user accounts\n")

for agent in agents:
    print(f"\n📝 Processing Agent: {agent.name}")
    print("-" * 80)
    
    # Create username from agent name
    base_username = slugify(agent.name.lower().replace(' ', '.'))
    username = base_username
    counter = 1
    
    # Make sure username is unique
    while User.objects.filter(username=username).exists():
        username = f"{base_username}{counter}"
        counter += 1
    
    # Use default password pattern
    password = f"{agent.name.lower().replace(' ', '.')}@123"
    
    try:
        # Create User account
        user = User.objects.create_user(
            username=username,
            email=agent.email or f"{username}@dsa.com",
            password=password,
            role='agent',  # Set role as 'agent'
            phone=agent.phone,
            is_active=True
        )
        
        # Link user to agent
        agent.user = user
        agent.save()
        
        print(f"✅ SUCCESS - User Created!")
        print(f"   Username: {username}")
        print(f"   Password: {password}")
        print(f"   Email: {user.email}")
        print(f"   Role: agent")
        
    except Exception as e:
        print(f"❌ ERROR: {str(e)}")

print("\n" + "=" * 80)
print("SUMMARY")
print("=" * 80)

agents_with_users = Agent.objects.filter(user__isnull=False).count()
total_agents = Agent.objects.count()

print(f"Agents with Users: {agents_with_users}/{total_agents}")
print(f"Agents without Users: {total_agents - agents_with_users}/{total_agents}")

print("\n✅ Agent login credentials have been set!")
print("\nAgents can now login with:")
print("  - Username: Their name (lowercase with dots)")
print("  - Password: name.with.dots@123")
print("\nExample:")
print("  - Username: laxman")
print("  - Password: laxman@123")
