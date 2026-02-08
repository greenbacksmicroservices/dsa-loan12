#!/usr/bin/env python
import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dsa_loan_management.settings')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

django.setup()

from core.models import User, Agent

print("=" * 80)
print("CHECKING EMPLOYEE & AGENT LOGIN CREDENTIALS")
print("=" * 80)

print("\n👥 EMPLOYEES (role='employee'):")
print("-" * 80)
employees = User.objects.filter(role='employee')
for emp in employees:
    has_password = bool(emp.password and emp.password != '')
    print(f"ID: {emp.id} | Username: {emp.username} | Email: {emp.email}")
    print(f"   Has Password: {has_password} | Password Hash: {emp.password[:30] if emp.password else 'EMPTY'}...")
    print()

print("\n💼 AGENTS:")
print("-" * 80)
agents = Agent.objects.all()
for agent in agents:
    if agent.user:
        has_password = bool(agent.user.password and agent.user.password != '')
        print(f"Agent ID: {agent.id} | Name: {agent.name} | Agent ID: {agent.agent_id}")
        print(f"   User ID: {agent.user.id} | Username: {agent.user.username} | Email: {agent.user.email}")
        print(f"   Has Password: {has_password} | Password Hash: {agent.user.password[:30] if agent.user.password else 'EMPTY'}...")
    else:
        print(f"Agent ID: {agent.id} | Name: {agent.name} | ⚠️ NO USER ASSOCIATED")
    print()

print("\n" + "=" * 80)
print("TOTAL SUMMARY")
print("=" * 80)
print(f"Total Employees: {employees.count()}")
print(f"Total Agents: {agents.count()}")
print(f"Agents with Users: {agents.filter(user__isnull=False).count()}")
print(f"Agents WITHOUT Users: {agents.filter(user__isnull=True).count()}")
