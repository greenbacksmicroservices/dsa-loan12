#!/usr/bin/env python
import os
import sys
import django

# Setup Django
sys.path.insert(0, r'd:\WEB DEVIOPMENT\DSA')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dsa_loan_management.settings')
django.setup()

from core.models import User, Agent

print("=" * 60)
print("CHECKING USER: lax@gmail.com")
print("=" * 60)

try:
    user = User.objects.get(email='lax@gmail.com')
    print(f"\n✓ USER FOUND:")
    print(f"  Username: {user.username}")
    print(f"  Email: {user.email}")
    print(f"  Role: {user.role}")
    print(f"  Is Active: {user.is_active}")
    print(f"  First Name: {user.first_name}")
    print(f"  Last Name: {user.last_name}")
    
    # Check agent profile
    try:
        agent = Agent.objects.get(user=user)
        print(f"\n✓ AGENT PROFILE EXISTS:")
        print(f"  Name: {agent.name}")
        print(f"  Phone: {agent.phone}")
        print(f"  Status: {agent.status}")
    except Agent.DoesNotExist:
        print(f"\n✗ NO AGENT PROFILE for this user")
        
except User.DoesNotExist:
    print(f"\n✗ USER NOT FOUND with email 'lax@gmail.com'")
    print(f"\nAvailable agents in database:")
    agents = Agent.objects.all()
    if agents:
        for agent in agents:
            print(f"  - {agent.name} (ID: {agent.id})")
            if agent.user:
                print(f"    User: {agent.user.username} ({agent.user.email})")
            else:
                print(f"    No user linked")
    else:
        print("  (No agents found)")

print("\n" + "=" * 60)
print("ALL USERS IN DATABASE:")
print("=" * 60)
users = User.objects.all()
if users:
    for u in users:
        print(f"\n- Username: {u.username}")
        print(f"  Email: {u.email}")
        print(f"  Role: {u.role}")
        print(f"  Active: {u.is_active}")
else:
    print("(No users found)")
