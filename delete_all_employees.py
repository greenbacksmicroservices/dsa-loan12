#!/usr/bin/env python
"""
Delete all employees from the database
Run with: python manage.py shell < delete_all_employees.py
Or from Django shell: exec(open('delete_all_employees.py').read())
"""

from django.contrib.auth.models import User
from app.models import Employee

print("Deleting all employees...")

# Get all users with role 'employee'
employees_users = User.objects.filter(profile__role='employee')
print(f"Found {employees_users.count()} employee users to delete")

# Delete Employee records
employee_records = Employee.objects.all()
count_records = employee_records.count()
employee_records.delete()
print(f"Deleted {count_records} employee records from Employee model")

# Delete User accounts
count_users = employees_users.count()
employees_users.delete()
print(f"Deleted {count_users} employee user accounts")

print("✅ All employees deleted successfully!")
