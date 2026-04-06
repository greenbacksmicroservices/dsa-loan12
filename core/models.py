from django.db import models
from django.contrib.auth.models import AbstractUser
from django.core.validators import RegexValidator
from django.utils import timezone


class User(AbstractUser):
    """Custom User Model with Role-based Access"""
    ROLE_CHOICES = [
        ('admin', 'Admin'),
        ('subadmin', 'SubAdmin'),
        ('dsa', 'DSA'),
        ('employee', 'Employee'),
        ('agent', 'Agent'),
    ]
    
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='employee')
    employee_id = models.CharField(max_length=50, unique=True, null=True, blank=True, help_text="Manual Employee ID")
    phone = models.CharField(max_length=15, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(
        max_length=10,
        choices=[('Male', 'Male'), ('Female', 'Female'), ('Other', 'Other')],
        null=True,
        blank=True
    )
    profile_photo = models.ImageField(upload_to='profile_photos/', blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'users'
    
    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"


class Agent(models.Model):
    """Agent/CP Model"""
    user = models.OneToOneField(User, on_delete=models.CASCADE, null=True, blank=True, related_name='agent_profile')
    agent_id = models.CharField(max_length=50, unique=True, null=True, blank=True, help_text="Manual Agent ID")
    name = models.CharField(max_length=100)
    phone = models.CharField(
        max_length=15,
        validators=[RegexValidator(regex=r'^\+?1?\d{9,15}$', message="Phone number must be entered in the format: '+999999999'. Up to 15 digits allowed.")]
    )
    email = models.EmailField(blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(
        max_length=10,
        choices=[('Male', 'Male'), ('Female', 'Female'), ('Other', 'Other')],
        null=True,
        blank=True
    )
    city = models.CharField(max_length=50, blank=True, null=True)
    state = models.CharField(max_length=50, blank=True, null=True)
    pin_code = models.CharField(max_length=6, blank=True, null=True)
    profile_photo = models.ImageField(upload_to='agent_photos/', blank=True, null=True)
    status = models.CharField(
        max_length=20,
        choices=[('active', 'Active'), ('blocked', 'Blocked')],
        default='active'
    )
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_agents')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'agents'
        ordering = ['-created_at']
    
    def __str__(self):
        return self.name
    
    @property
    def total_leads(self):
        return self.loans.count()
    
    @property
    def approved_loans_count(self):
        return self.loans.filter(status='approved').count()
    
    @property
    def total_disbursed_amount(self):
        return self.loans.filter(status='disbursed').aggregate(
            total=models.Sum('loan_amount')
        )['total'] or 0
    
    @property
    def commission(self):
        # Assuming 2% commission on disbursed loans
        from decimal import Decimal
        return self.total_disbursed_amount * Decimal('0.02')


class Loan(models.Model):
    """Enhanced Loan Entry Model"""
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('new_entry', 'New Entry'),
        ('waiting', 'Waiting for Processing'),
        ('follow_up', 'Banking Processing'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('disputed', 'Disputed'),
        ('disbursed', 'Disbursed'),
        ('forclose', 'For Close'),
    ]
    
    LOAN_TYPE_CHOICES = [
        ('personal', 'Personal Loan'),
        ('lap', 'LAP (Loan Against Property)'),
        ('home', 'Home Loan'),
        ('business', 'Business Loan'),
        ('education', 'Education Loan'),
        ('car', 'Car Loan'),
        ('other', 'Other'),
    ]

    APPLICANT_TYPE_CHOICES = [
        ('employee', 'Employee'),
        ('agent', 'Agent'),
    ]

    BANK_TYPE_CHOICES = [
        ('private', 'Private'),
        ('government', 'Government'),
        ('cooperative', 'Cooperative'),
        ('nbfc', 'NBFC'),
    ]
    
    # Applicant Details
    full_name = models.CharField(max_length=100)
    user_id = models.CharField(max_length=20, unique=True, blank=True, null=True)  # Auto-generated
    username = models.CharField(max_length=50, blank=True, null=True)
    password = models.CharField(max_length=255, blank=True, null=True)
    mobile_number = models.CharField(
        max_length=15,
        validators=[RegexValidator(regex=r'^\+?1?\d{9,15}$', message="Phone number must be entered in the format: '+999999999'. Up to 15 digits allowed.")]
    )
    email = models.EmailField(blank=True, null=True)
    city = models.CharField(max_length=50, blank=True, null=True)
    state = models.CharField(max_length=50, blank=True, null=True)
    pin_code = models.CharField(max_length=6, blank=True, null=True)
    permanent_address = models.TextField(blank=True, null=True)
    current_address = models.TextField(blank=True, null=True)
    
    # Loan Details
    loan_type = models.CharField(max_length=50, choices=LOAN_TYPE_CHOICES)
    loan_amount = models.DecimalField(max_digits=15, decimal_places=2)
    tenure_months = models.IntegerField(blank=True, null=True)
    interest_rate = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    emi = models.DecimalField(max_digits=15, decimal_places=2, blank=True, null=True)  # Auto-calculated
    loan_purpose = models.CharField(max_length=200, blank=True, null=True)
    
    # Bank Details
    bank_name = models.CharField(max_length=100, blank=True, null=True)
    bank_account_number = models.CharField(max_length=50, blank=True, null=True)
    bank_ifsc_code = models.CharField(max_length=20, blank=True, null=True)
    bank_type = models.CharField(max_length=20, choices=BANK_TYPE_CHOICES, blank=True, null=True)
    
    # Status & Assignment
    applicant_type = models.CharField(max_length=20, choices=APPLICANT_TYPE_CHOICES, default='employee')
    assigned_employee = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='loans_as_employee')
    assigned_agent = models.ForeignKey(Agent, on_delete=models.SET_NULL, null=True, blank=True, related_name='loans')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='new_entry')
    
    # Assignment & Follow-up Tracking (for 4-hour rule)
    assigned_at = models.DateTimeField(null=True, blank=True)  # When assigned to employee/agent
    action_taken_at = models.DateTimeField(null=True, blank=True)  # When approved/rejected
    follow_up_triggered_at = models.DateTimeField(null=True, blank=True)  # When auto-moved to follow-up
    requires_follow_up = models.BooleanField(default=False)  # Tracks if follow-up was auto-triggered
    
    # Co-applicant
    has_co_applicant = models.BooleanField(default=False)
    co_applicant_name = models.CharField(max_length=100, blank=True, null=True)
    co_applicant_phone = models.CharField(max_length=15, blank=True, null=True)
    co_applicant_email = models.EmailField(blank=True, null=True)
    
    # Guarantor
    has_guarantor = models.BooleanField(default=False)
    guarantor_name = models.CharField(max_length=100, blank=True, null=True)
    guarantor_phone = models.CharField(max_length=15, blank=True, null=True)
    guarantor_email = models.EmailField(blank=True, null=True)
    
    # Remarks
    remarks = models.TextField(blank=True, null=True)
    sm_name = models.CharField(max_length=120, blank=True, null=True)
    sm_phone_number = models.CharField(max_length=20, blank=True, null=True)
    sm_email = models.EmailField(blank=True, null=True)
    is_sm_signed = models.BooleanField(default=False)
    sm_signed_at = models.DateTimeField(null=True, blank=True)
    
    # Metadata
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_loans')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Helper methods for 4-hour follow-up automation
    def is_overdue_for_followup(self):
        """Check if 4 hours have passed since assignment without action"""
        from django.utils import timezone
        from datetime import timedelta
        
        if not self.assigned_at or self.action_taken_at:
            return False
        
        time_elapsed = timezone.now() - self.assigned_at
        return time_elapsed >= timedelta(hours=4)
    
    def get_hours_since_assignment(self):
        """Get hours elapsed since assignment"""
        from django.utils import timezone
        
        if not self.assigned_at:
            return 0
        
        time_elapsed = timezone.now() - self.assigned_at
        return int(time_elapsed.total_seconds() / 3600)
    
    class Meta:
        db_table = 'loans'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.full_name} - {self.loan_type} ({self.status})"
    
    def save(self, *args, **kwargs):
        # Auto-generate User ID if not present
        if not self.user_id:
            from datetime import datetime
            timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
            self.user_id = f"USR{timestamp}"
        
        # Auto-calculate EMI
        if self.loan_amount and self.tenure_months and self.interest_rate:
            principal = float(self.loan_amount)
            monthly_rate = float(self.interest_rate) / 100 / 12
            num_payments = int(self.tenure_months)
            
            if monthly_rate > 0:
                emi = (principal * monthly_rate * (1 + monthly_rate) ** num_payments) / \
                      ((1 + monthly_rate) ** num_payments - 1)
                self.emi = round(emi, 2)
            else:
                self.emi = principal / num_payments if num_payments > 0 else principal
        
        super().save(*args, **kwargs)


class LoanDocument(models.Model):
    """Document Upload Model for Loans"""
    DOCUMENT_TYPE_CHOICES = [
        ('pan_card', 'PAN Card'),
        ('aadhaar_card', 'Aadhaar Card'),
        ('applicant_photo', 'Applicant Photo'),
        ('permanent_address_proof', 'Permanent Address Proof'),
        ('current_address_proof', 'Current Address Proof'),
        ('salary_slip', 'Salary Slip'),
        ('bank_statement', 'Bank Statement'),
        ('form_16', 'Form 16'),
        ('service_book', 'Service Book'),
        ('property_documents', 'Property Documents'),
        ('soa_existing_loan', 'SOA of Existing Loan Account'),
        ('forclosure_document', 'Forcloser Document'),
        ('co_applicant_pan', 'Co-applicant PAN'),
        ('co_applicant_aadhaar', 'Co-applicant Aadhaar'),
        ('co_applicant_photo', 'Co-applicant Photo'),
        ('guarantor_pan', 'Guarantor PAN'),
        ('guarantor_aadhaar', 'Guarantor Aadhaar'),
        ('guarantor_address_proof', 'Guarantor Address Proof'),
        ('other', 'Other'),
    ]
    
    MANDATORY_DOCUMENTS = [
        'pan_card', 'aadhaar_card', 'applicant_photo', 
        'permanent_address_proof', 'current_address_proof'
    ]
    
    loan = models.ForeignKey(Loan, on_delete=models.CASCADE, related_name='documents')
    document_type = models.CharField(max_length=50, choices=DOCUMENT_TYPE_CHOICES)
    file = models.FileField(upload_to='loan_documents/%Y/%m/%d/')
    is_required = models.BooleanField(default=False)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'loan_documents'
        unique_together = ('loan', 'document_type')
    
    def __str__(self):
        return f"{self.loan.full_name} - {self.get_document_type_display()}"


class Complaint(models.Model):
    """Complaint Model"""
    PRIORITY_CHOICES = [
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('urgent', 'Urgent'),
    ]
    
    STATUS_CHOICES = [
        ('open', 'Open'),
        ('in_progress', 'In Progress'),
        ('resolved', 'Resolved'),
        ('closed', 'Closed'),
    ]
    
    COMPLAINT_TYPE_CHOICES = [
        ('service', 'Service Issue'),
        ('payment', 'Payment Issue'),
        ('documentation', 'Documentation Issue'),
        ('other', 'Other'),
    ]
    
    complaint_id = models.CharField(max_length=50, unique=True)
    customer_name = models.CharField(max_length=100)
    loan = models.ForeignKey(Loan, on_delete=models.CASCADE, related_name='complaints', null=True, blank=True)
    # Link to employee or agent who filed the complaint
    filed_by_employee = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='employee_complaints', limit_choices_to={'role': 'employee'})
    filed_by_agent = models.ForeignKey(Agent, on_delete=models.SET_NULL, null=True, blank=True, related_name='agent_complaints')
    complaint_type = models.CharField(max_length=50, choices=COMPLAINT_TYPE_CHOICES)
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default='medium')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='open')
    description = models.TextField()
    assigned_admin = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_complaints')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_complaints')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        db_table = 'complaints'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.complaint_id} - {self.customer_name}"
    
    def save(self, *args, **kwargs):
        if not self.complaint_id:
            # Generate complaint ID
            last_complaint = Complaint.objects.order_by('-id').first()
            if last_complaint:
                last_id = int(last_complaint.complaint_id.split('-')[-1]) if '-' in last_complaint.complaint_id else 0
                self.complaint_id = f"COMP-{last_id + 1:06d}"
            else:
                self.complaint_id = "COMP-000001"
        super().save(*args, **kwargs)


class ComplaintComment(models.Model):
    """Complaint Comment/History Model"""
    complaint = models.ForeignKey(Complaint, on_delete=models.CASCADE, related_name='comments')
    comment = models.TextField()
    commented_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'complaint_comments'
        ordering = ['created_at']
    
    def __str__(self):
        return f"Comment on {self.complaint.complaint_id}"


class ActivityLog(models.Model):
    """Activity Log Model for Recent Activity Panel"""
    ACTION_CHOICES = [
        ('loan_added', 'New Loan Added'),
        ('status_updated', 'Status Updated'),
        ('agent_registered', 'New Agent Registered'),
        ('complaint_raised', 'Complaint Raised'),
        ('loan_approved', 'Loan Approved'),
        ('loan_rejected', 'Loan Rejected'),
        ('loan_disbursed', 'Loan Disbursed'),
    ]
    
    action = models.CharField(max_length=50, choices=ACTION_CHOICES)
    description = models.TextField()
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    related_loan = models.ForeignKey(Loan, on_delete=models.SET_NULL, null=True, blank=True)
    related_agent = models.ForeignKey(Agent, on_delete=models.SET_NULL, null=True, blank=True)
    related_complaint = models.ForeignKey(Complaint, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'activity_logs'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.get_action_display()} - {self.created_at}"


class Applicant(models.Model):
    """Applicant Model for Multi-Step Registration"""
    ROLE_CHOICES = [
        ('employee', 'Employee'),
        ('agent', 'Agent'),
    ]
    
    GENDER_CHOICES = [
        ('male', 'Male'),
        ('female', 'Female'),
        ('other', 'Other'),
    ]
    
    BANK_TYPE_CHOICES = [
        ('private', 'Private'),
        ('government', 'Government'),
        ('cooperative', 'Cooperative'),
        ('nbfc', 'NBFC'),
    ]
    
    LOAN_TYPE_CHOICES = [
        ('personal', 'Personal Loan'),
        ('lap', 'LAP (Loan Against Property)'),
        ('home', 'Home Loan'),
        ('business', 'Business Loan'),
        ('education', 'Education Loan'),
        ('car', 'Car Loan'),
        ('other', 'Other'),
    ]
    
    # Step 1: Applicant Details
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    full_name = models.CharField(max_length=200)
    username = models.CharField(max_length=100, unique=True)
    mobile = models.CharField(max_length=15)
    email = models.EmailField()
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100)
    pin_code = models.CharField(max_length=10)
    gender = models.CharField(max_length=10, choices=GENDER_CHOICES)
    
    # Step 2: Loan & Bank Details
    loan_type = models.CharField(max_length=50, choices=LOAN_TYPE_CHOICES, blank=True, null=True)
    loan_amount = models.DecimalField(max_digits=15, decimal_places=2, blank=True, null=True)
    tenure_months = models.IntegerField(blank=True, null=True)
    interest_rate = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    emi = models.DecimalField(max_digits=15, decimal_places=2, blank=True, null=True)
    loan_purpose = models.TextField(blank=True, null=True)
    
    # Bank Details
    bank_name = models.CharField(max_length=200, blank=True, null=True)
    bank_type = models.CharField(max_length=20, choices=BANK_TYPE_CHOICES, blank=True, null=True)
    account_number = models.CharField(max_length=50, blank=True, null=True)
    ifsc_code = models.CharField(max_length=20, blank=True, null=True)
    
    # Step 3: Status & Metadata
    status = models.CharField(max_length=50, default='New Entry')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'applicants'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.full_name} ({self.role})"
    
    def calculate_emi(self):
        """Calculate EMI using formula: EMI = [P x R x (1+R)^N] / [(1+R)^N â€“ 1]"""
        if self.loan_amount and self.tenure_months and self.interest_rate:
            principal = float(self.loan_amount)
            monthly_rate = float(self.interest_rate) / 100 / 12
            num_payments = int(self.tenure_months)
            
            if monthly_rate > 0:
                numerator = principal * monthly_rate * ((1 + monthly_rate) ** num_payments)
                denominator = ((1 + monthly_rate) ** num_payments) - 1
                emi = numerator / denominator
                return round(emi, 2)
            else:
                return round(principal / num_payments, 2) if num_payments > 0 else principal
        return 0
    
    def save(self, *args, **kwargs):
        # Auto-calculate EMI
        if self.loan_amount and self.tenure_months and self.interest_rate:
            self.emi = self.calculate_emi()
        super().save(*args, **kwargs)


class LoanApplication(models.Model):
    """Enhanced Loan Application Model with Workflow Automation"""
    STATUS_CHOICES = [
        ('New Entry', 'New Entry'),
        ('Waiting for Processing', 'Waiting for Processing'),
        ('Required Follow-up', 'Banking Processing'),
        ('Approved', 'Approved'),
        ('Rejected', 'Rejected'),
        ('Disbursed', 'Disbursed'),
    ]
    
    applicant = models.OneToOneField(Applicant, on_delete=models.CASCADE, related_name='loan_application')
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default='New Entry')
    
    # Assignment Fields
    assigned_agent = models.ForeignKey(Agent, on_delete=models.SET_NULL, null=True, blank=True, related_name='loan_applications')
    assigned_employee = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, limit_choices_to={'role': 'employee'}, related_name='assigned_loan_applications')
    assigned_at = models.DateTimeField(null=True, blank=True)
    assigned_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='assignments_made')
    
    # Approval Fields
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_loans')
    approval_notes = models.TextField(blank=True, null=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    sm_name = models.CharField(max_length=120, blank=True, null=True)
    sm_phone_number = models.CharField(max_length=20, blank=True, null=True)
    sm_email = models.EmailField(blank=True, null=True)
    is_sm_signed = models.BooleanField(default=False)
    sm_signed_at = models.DateTimeField(null=True, blank=True)
    
    # Rejection Fields
    rejected_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='rejected_loans')
    rejection_reason = models.TextField(blank=True, null=True)
    rejected_at = models.DateTimeField(null=True, blank=True)
    
    # Follow-up Fields (Automation)
    follow_up_scheduled_at = models.DateTimeField(null=True, blank=True, help_text="When follow-up was scheduled")
    follow_up_notified_at = models.DateTimeField(null=True, blank=True, help_text="When follow-up notification was sent")
    follow_up_count = models.IntegerField(default=0, help_text="Number of follow-ups triggered")
    
    # Disbursement Fields
    disbursed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='disbursed_loans')
    disbursed_at = models.DateTimeField(null=True, blank=True)
    disbursement_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'loan_applications'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['assigned_employee']),
            models.Index(fields=['assigned_agent']),
        ]
    
    def __str__(self):
        return f"{self.applicant.full_name} - {self.status}"
    
    @property
    def is_new_entry(self):
        return self.status == 'New Entry'
    
    @property
    def is_waiting(self):
        return self.status == 'Waiting for Processing'
    
    @property
    def is_follow_up(self):
        return self.status == 'Required Follow-up'
    
    @property
    def is_approved(self):
        return self.status == 'Approved'
    
    @property
    def is_rejected(self):
        return self.status == 'Rejected'
    
    @property
    def hours_since_assignment(self):
        """Returns hours elapsed since assignment"""
        if not self.assigned_at:
            return None
        from django.utils import timezone
        return (timezone.now() - self.assigned_at).total_seconds() / 3600
    
    @property
    def requires_follow_up(self):
        """Check if application has been waiting > 4 hours"""
        if self.is_waiting and self.hours_since_assignment:
            return self.hours_since_assignment > 4
        return False
    
    def trigger_follow_up(self):
        """Move status to Required Follow-up"""
        from django.utils import timezone
        self.status = 'Required Follow-up'
        self.follow_up_scheduled_at = timezone.now()
        self.follow_up_notified_at = timezone.now()
        self.follow_up_count += 1
        self.save()
        return True


class ApplicantDocument(models.Model):
    """Document Upload Model for Applicants"""
    DOCUMENT_TYPE_CHOICES = [
        ('photo', 'Applicant Photo'),
        ('pan_front', 'PAN Card Front'),
        ('pan_back', 'PAN Card Back'),
        ('aadhaar_front', 'Aadhaar Front'),
        ('aadhaar_back', 'Aadhaar Back'),
        ('permanent_address', 'Permanent Address Proof'),
        ('current_address', 'Current Address Proof'),
        ('salary_slip', 'Salary Slip'),
        ('bank_statement', 'Bank Statement'),
        ('form_16', 'Form 16'),
        ('service_book', 'Service Book'),
    ]
    
    loan_application = models.ForeignKey(LoanApplication, on_delete=models.CASCADE, related_name='documents')
    document_type = models.CharField(max_length=50, choices=DOCUMENT_TYPE_CHOICES)
    file = models.FileField(upload_to='applicant_documents/%Y/%m/%d/')
    is_required = models.BooleanField(default=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'applicant_documents'
        unique_together = ('loan_application', 'document_type')
    
    def __str__(self):
        return f"{self.loan_application.applicant.full_name} - {self.get_document_type_display()}"


class EmployeeProfile(models.Model):
    """Employee Profile Model - Extended User Information"""
    ROLE_CHOICES = [
        ('loan_processor', 'Loan Processor'),
        ('verification', 'Verification Officer'),
        ('manager', 'Manager'),
    ]
    
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='employee_profile')
    employee_role = models.CharField(max_length=50, choices=ROLE_CHOICES, default='loan_processor')
    total_leads = models.PositiveIntegerField(default=0)
    approved_loans = models.PositiveIntegerField(default=0)
    rejected_loans = models.PositiveIntegerField(default=0)
    total_disbursed_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    
    # Additional fields
    assigned_loans_count = models.PositiveIntegerField(default=0)
    last_activity = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'employee_profiles'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.user.get_full_name()} ({self.get_employee_role_display()})"
    
    @property
    def total_loans(self):
        """Total loans processed = approved + rejected"""
        return self.approved_loans + self.rejected_loans
    
    @property
    def approval_rate(self):
        """Approval rate percentage"""
        if self.total_loans == 0:
            return 0
        return round((self.approved_loans / self.total_loans) * 100, 2)


class UserOnboardingProfile(models.Model):
    """Store extended onboarding/KYC data for employees, agents, and subadmins"""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='onboarding_profile')
    role = models.CharField(max_length=20, blank=True, null=True)
    data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'user_onboarding_profiles'
        ordering = ['-created_at']

    def __str__(self):
        return f"Onboarding - {self.user.username}"


class UserOnboardingDocument(models.Model):
    """Documents uploaded during onboarding"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='onboarding_documents')
    document_type = models.CharField(max_length=50, default='other', blank=True)
    file = models.FileField(upload_to='user_documents/%Y/%m/%d/')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'user_onboarding_documents'
        ordering = ['-uploaded_at']

    def __str__(self):
        return f"{self.user.username} - {self.document_type}"


class LoanStatusHistory(models.Model):
    """Track all status changes for loans"""
    STATUS_CHOICES = [
        ('new_entry', 'New Entry'),
        ('waiting', 'Waiting for Processing'),
        ('follow_up', 'Banking Processing'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('disbursed', 'Disbursed'),
    ]
    
    loan_application = models.ForeignKey(LoanApplication, on_delete=models.CASCADE, related_name='status_history')
    from_status = models.CharField(max_length=50, choices=STATUS_CHOICES, null=True, blank=True)
    to_status = models.CharField(max_length=50, choices=STATUS_CHOICES)
    changed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    changed_at = models.DateTimeField(auto_now_add=True)
    reason = models.TextField(blank=True, null=True)
    is_auto_triggered = models.BooleanField(default=False, help_text="True if auto-moved (e.g., follow-up)")
    
    class Meta:
        db_table = 'loan_status_history'
        ordering = ['-changed_at']
        indexes = [
            models.Index(fields=['loan_application', '-changed_at']),
            models.Index(fields=['to_status']),
        ]
    
    def __str__(self):
        return f"{self.loan_application.id}: {self.from_status} â†’ {self.to_status}"


class LoanAssignment(models.Model):
    """Track assignments of loans to employees"""
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('completed', 'Completed'),
        ('reassigned', 'Reassigned'),
    ]
    
    loan_application = models.ForeignKey(LoanApplication, on_delete=models.CASCADE, related_name='assignments')
    assigned_to = models.ForeignKey(User, on_delete=models.CASCADE, limit_choices_to={'role': 'employee'}, related_name='assigned_loans_history')
    assigned_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='assignments_created')
    assigned_at = models.DateTimeField(auto_now_add=True)
    
    # Completion tracking
    completed_at = models.DateTimeField(null=True, blank=True)
    reassigned_at = models.DateTimeField(null=True, blank=True)
    
    # Status of this assignment
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    
    # Notes
    assignment_notes = models.TextField(blank=True, null=True)
    
    class Meta:
        db_table = 'loan_assignments'
        ordering = ['-assigned_at']
        indexes = [
            models.Index(fields=['assigned_to', 'status']),
            models.Index(fields=['loan_application']),
        ]
    
    def __str__(self):
        return f"Assigned: {self.loan_application.id} â†’ {self.assigned_to.get_full_name()}"
    
    @property
    def hours_assigned(self):
        """Calculate hours this assignment has been active"""
        if not self.assigned_at:
            return 0
        from django.utils import timezone
        return int((timezone.now() - self.assigned_at).total_seconds() / 3600)
    
    def complete(self, completed_at=None):
        """Mark assignment as completed"""
        from django.utils import timezone
        self.completed_at = completed_at or timezone.now()
        self.status = 'completed'
        self.save()
    
    def reassign(self, new_employee, reassigned_at=None):
        """Mark assignment as reassigned"""
        from django.utils import timezone
        self.reassigned_at = reassigned_at or timezone.now()
        self.status = 'reassigned'
        self.save()


class AgentAssignment(models.Model):
    """
    Model to track which agents are assigned to which employees
    Allows admin to manage agent-employee relationships
    """
    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name='employee_assignments')
    employee = models.ForeignKey(User, on_delete=models.CASCADE, limit_choices_to={'role': 'employee'}, related_name='agent_assignments')
    assigned_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='agent_assignments_created')
    assigned_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ('agent', 'employee')
        db_table = 'agent_assignments'
        ordering = ['-assigned_at']
    
    def __str__(self):
        return f"{self.agent.name} â†’ {self.employee.get_full_name()}"


class SubAdminEntry(models.Model):
    """
    Model for SubAdmin to create and track new entries
    Each SubAdmin can add loan application details which are stored and displayed in a table
    """
    STATUS_CHOICES = [
        ('New Entry', 'New Entry'),
        ('Waiting for Processing', 'Waiting for Processing'),
        ('Required Follow-up', 'Banking Processing'),
        ('Approved', 'Approved'),
        ('Rejected', 'Rejected'),
        ('Disbursed', 'Disbursed'),
    ]
    
    subadmin = models.ForeignKey(User, on_delete=models.CASCADE, related_name='subadmin_entries', limit_choices_to={'role': 'subadmin'})
    
    # Applicant Information
    applicant_name = models.CharField(max_length=150)
    applicant_phone = models.CharField(max_length=15)
    applicant_email = models.EmailField()
    
    # Loan Details
    loan_amount = models.DecimalField(max_digits=12, decimal_places=2)
    loan_type = models.CharField(
        max_length=50,
        choices=[
            ('Personal Loan', 'Personal Loan'),
            ('Business Loan', 'Business Loan'),
            ('Home Loan', 'Home Loan'),
            ('Education Loan', 'Education Loan'),
            ('Auto Loan', 'Auto Loan'),
        ],
        default='Personal Loan'
    )
    loan_tenure = models.IntegerField(help_text="Loan tenure in months")
    interest_rate = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    
    # Status
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default='New Entry')
    
    # Additional Details
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'subadmin_entries'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['subadmin', '-created_at']),
            models.Index(fields=['status']),
        ]
    
    def __str__(self):
        return f"{self.applicant_name} - {self.loan_type} (â‚¹{self.loan_amount})"


