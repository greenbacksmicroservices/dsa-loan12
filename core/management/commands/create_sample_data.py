from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from core.models import Agent, Loan, Complaint, ActivityLog
from decimal import Decimal
from datetime import datetime, timedelta
import random

User = get_user_model()


class Command(BaseCommand):
    help = 'Create sample data for testing'

    def add_arguments(self, parser):
        parser.add_argument(
            '--agents',
            type=int,
            default=5,
            help='Number of agents to create',
        )
        parser.add_argument(
            '--loans',
            type=int,
            default=50,
            help='Number of loans to create',
        )
        parser.add_argument(
            '--complaints',
            type=int,
            default=10,
            help='Number of complaints to create',
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Creating sample data...'))

        # Create agents
        agents = []
        for i in range(options['agents']):
            agent = Agent.objects.create(
                name=f'Agent {i+1}',
                phone=f'987654321{i}',
                email=f'agent{i+1}@example.com',
                address=f'Address {i+1}',
                status='active'
            )
            agents.append(agent)
            self.stdout.write(f'Created agent: {agent.name}')

        # Create loans
        loan_types = ['personal', 'home', 'car', 'business', 'education']
        statuses = ['new_entry', 'waiting', 'follow_up', 'approved', 'rejected', 'disbursed']
        banks = ['HDFC Bank', 'ICICI Bank', 'SBI', 'Axis Bank', 'Kotak Bank']

        for i in range(options['loans']):
            # Random date within last 6 months
            days_ago = random.randint(0, 180)
            created_at = datetime.now() - timedelta(days=days_ago)

            loan = Loan.objects.create(
                customer_name=f'Customer {i+1}',
                mobile_number=f'987654321{i%10}',
                loan_type=random.choice(loan_types),
                loan_amount=Decimal(random.randint(50000, 5000000)),
                bank_name=random.choice(banks),
                assigned_agent=random.choice(agents) if agents else None,
                status=random.choice(statuses),
                remarks=f'Sample loan {i+1}'
            )
            # Update created_at
            loan.created_at = created_at
            loan.save(update_fields=['created_at'])

        self.stdout.write(f'Created {options["loans"]} loans')

        # Create complaints
        complaint_types = ['service', 'payment', 'documentation', 'other']
        priorities = ['low', 'medium', 'high', 'urgent']
        complaint_statuses = ['open', 'in_progress', 'resolved', 'closed']

        loans = Loan.objects.all()
        for i in range(options['complaints']):
            Complaint.objects.create(
                customer_name=f'Customer {i+1}',
                loan=random.choice(loans) if loans.exists() else None,
                complaint_type=random.choice(complaint_types),
                priority=random.choice(priorities),
                status=random.choice(complaint_statuses),
                description=f'Sample complaint {i+1}'
            )

        self.stdout.write(f'Created {options["complaints"]} complaints')
        self.stdout.write(self.style.SUCCESS('Sample data created successfully!'))


