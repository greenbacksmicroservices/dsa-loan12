#!/usr/bin/env python
import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dsa_loan_management.settings')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

django.setup()

from core.models import User, Agent

print("=" * 80)
print("CHECKING USER ROLES")
print("=" * 80)

print("\n👥 EMPLOYEES:")
employees = User.objects.filter(role='employee')
for emp in employees:
    print(f"  {emp.username} - Role: {emp.role} ✅")

print("\n💼 AGENTS:")
agents = Agent.objects.all()
for agent in agents:
    if agent.user:
        print(f"  {agent.user.username} - Role: {agent.user.role} {'✅' if agent.user.role == 'agent' else '❌'}")
    else:
        print(f"  {agent.name} - NO USER")

print("\n👨‍💼 ADMINS:")
admins = User.objects.filter(role='admin')
for admin in admins:
    print(f"  {admin.username} - Role: {admin.role} ✅")

print("\n" + "=" * 80)
