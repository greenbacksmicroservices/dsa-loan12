from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

User = get_user_model()


class Command(BaseCommand):
    help = 'Create an admin user for the DSA Loan Management System'

    def add_arguments(self, parser):
        parser.add_argument(
            '--username',
            type=str,
            default='admin',
            help='Username for admin user',
        )
        parser.add_argument(
            '--email',
            type=str,
            default='admin@dsa.com',
            help='Email for admin user',
        )
        parser.add_argument(
            '--password',
            type=str,
            help='Password for admin user (if not provided, will prompt)',
        )

    def handle(self, *args, **options):
        username = options['username']
        email = options['email']
        password = options['password']
        
        # Check if user already exists
        if User.objects.filter(username=username).exists():
            self.stdout.write(self.style.WARNING(f'User "{username}" already exists.'))
            return
        
        # Prompt for password if not provided
        if not password:
            password = self.get_password()
        
        # Create admin user
        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            role='admin',
            is_staff=True,
            is_superuser=True
        )
        
        self.stdout.write(self.style.SUCCESS(f'Successfully created admin user: {username}'))
        self.stdout.write(self.style.SUCCESS(f'Email: {email}'))
        self.stdout.write(self.style.SUCCESS(f'Role: Admin'))
        self.stdout.write(self.style.WARNING('Please keep these credentials secure!'))
    
    def get_password(self):
        """Get password from user input"""
        import getpass
        password = getpass.getpass('Enter password: ')
        password_confirm = getpass.getpass('Confirm password: ')
        
        if password != password_confirm:
            self.stdout.write(self.style.ERROR('Passwords do not match!'))
            return self.get_password()
        
        if len(password) < 8:
            self.stdout.write(self.style.ERROR('Password must be at least 8 characters long!'))
            return self.get_password()
        
        return password

