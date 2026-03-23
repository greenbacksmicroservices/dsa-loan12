
#!/usr/bin/env python
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dsa_loan_management.settings')
django.setup()

from django.contrib.auth import get_user_model

User = get_user_model()

# Check existing subadmin users
users = User.objects.filter(role='subadmin').values('email', 'username', 'role')[:5]
print('Subadmin users:')
for u in users:
    print(f"  Email: {u['email']}, Username: {u['username']}")

if not users.exists():
    print('\nNo subadmin users found. Creating one...')
    user = User.objects.create_user(
        email='subadmin@test.com',
        username='subadmin',
        password='subadmin123',
        role='subadmin',
        first_name='Sub',
        last_name='Admin'
    )
    print(f'Created: {user.email}')
else:
    print(f'\nTotal subadmin users: {User.objects.filter(role="subadmin").count()}')
