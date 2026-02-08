# Generated migration file for new registration models

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0004_loan_bank_account_number_loan_bank_ifsc_code_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='Applicant',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('role', models.CharField(choices=[('employee', 'Employee'), ('agent', 'Agent')], max_length=20)),
                ('full_name', models.CharField(max_length=200)),
                ('username', models.CharField(max_length=100, unique=True)),
                ('mobile', models.CharField(max_length=15)),
                ('email', models.EmailField(max_length=254)),
                ('city', models.CharField(max_length=100)),
                ('state', models.CharField(max_length=100)),
                ('pin_code', models.CharField(max_length=10)),
                ('gender', models.CharField(choices=[('male', 'Male'), ('female', 'Female'), ('other', 'Other')], max_length=10)),
                ('loan_type', models.CharField(blank=True, choices=[('personal', 'Personal Loan'), ('lap', 'LAP (Loan Against Property)'), ('home', 'Home Loan'), ('business', 'Business Loan'), ('education', 'Education Loan'), ('car', 'Car Loan'), ('other', 'Other')], max_length=50, null=True)),
                ('loan_amount', models.DecimalField(blank=True, decimal_places=2, max_digits=15, null=True)),
                ('tenure_months', models.IntegerField(blank=True, null=True)),
                ('interest_rate', models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True)),
                ('emi', models.DecimalField(blank=True, decimal_places=2, max_digits=15, null=True)),
                ('loan_purpose', models.TextField(blank=True, null=True)),
                ('bank_name', models.CharField(blank=True, max_length=200, null=True)),
                ('bank_type', models.CharField(blank=True, choices=[('private', 'Private'), ('government', 'Government'), ('cooperative', 'Cooperative'), ('nbfc', 'NBFC')], max_length=20, null=True)),
                ('account_number', models.CharField(blank=True, max_length=50, null=True)),
                ('ifsc_code', models.CharField(blank=True, max_length=20, null=True)),
                ('status', models.CharField(default='New Entry', max_length=50)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'db_table': 'applicants',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='LoanApplication',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(choices=[('New Entry', 'New Entry'), ('Processing', 'Processing'), ('Approved', 'Approved'), ('Rejected', 'Rejected'), ('Disbursed', 'Disbursed')], default='New Entry', max_length=50)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('applicant', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='loan_application', to='core.applicant')),
                ('assigned_agent', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='loan_applications', to='core.agent')),
                ('assigned_employee', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='assigned_loan_applications', to='core.user')),
            ],
            options={
                'db_table': 'loan_applications',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='ApplicantDocument',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('document_type', models.CharField(choices=[('photo', 'Applicant Photo'), ('pan_front', 'PAN Card Front'), ('pan_back', 'PAN Card Back'), ('aadhaar_front', 'Aadhaar Front'), ('aadhaar_back', 'Aadhaar Back'), ('permanent_address', 'Permanent Address Proof'), ('current_address', 'Current Address Proof'), ('salary_slip', 'Salary Slip'), ('bank_statement', 'Bank Statement'), ('form_16', 'Form 16'), ('service_book', 'Service Book')], max_length=50)),
                ('file', models.FileField(upload_to='applicant_documents/%Y/%m/%d/')),
                ('is_required', models.BooleanField(default=True)),
                ('uploaded_at', models.DateTimeField(auto_now_add=True)),
                ('loan_application', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='documents', to='core.loanapplication')),
            ],
            options={
                'db_table': 'applicant_documents',
                'unique_together': {('loan_application', 'document_type')},
            },
        ),
    ]
