from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, Agent, Loan, Complaint, ComplaintComment, ActivityLog, Applicant, LoanApplication, ApplicantDocument


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ['username', 'email', 'role', 'phone', 'is_active', 'created_at']
    list_filter = ['role', 'is_active', 'created_at']
    fieldsets = BaseUserAdmin.fieldsets + (
        ('Additional Info', {
            'fields': ('role', 'phone', 'employee_id', 'profile_photo', 'date_of_birth', 'gender', 'address')
        }),
        ('Important Dates', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ('Additional Info', {
            'fields': ('role', 'phone', 'employee_id', 'profile_photo', 'date_of_birth', 'gender', 'address')
        }),
    )
    readonly_fields = ['created_at', 'updated_at']


@admin.register(Agent)
class AgentAdmin(admin.ModelAdmin):
    list_display = ['name', 'phone', 'email', 'status', 'date_of_birth', 'gender', 'created_at']
    list_filter = ['status', 'gender', 'created_at']
    search_fields = ['name', 'phone', 'email', 'agent_id']
    readonly_fields = ['created_at', 'updated_at']
    
    fieldsets = (
        ('Agent Details', {
            'fields': ('user', 'agent_id', 'name', 'phone', 'email', 'profile_photo')
        }),
        ('Personal Information', {
            'fields': ('date_of_birth', 'gender')
        }),
        ('Address', {
            'fields': ('address', 'city', 'state', 'pin_code')
        }),
        ('Status', {
            'fields': ('status', 'created_by')
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    add_fieldsets = (
        ('Agent Details', {
            'fields': ('user', 'agent_id', 'name', 'phone', 'email', 'profile_photo')
        }),
        ('Personal Information', {
            'fields': ('date_of_birth', 'gender')
        }),
        ('Address', {
            'fields': ('address', 'city', 'state', 'pin_code')
        }),
        ('Status', {
            'fields': ('status',)
        }),
    )


@admin.register(Applicant)
class ApplicantAdmin(admin.ModelAdmin):
    list_display = ['full_name', 'role', 'mobile', 'email', 'loan_type', 'loan_amount', 'created_at']
    list_filter = ['role', 'loan_type', 'created_at']
    search_fields = ['full_name', 'mobile', 'email', 'username']
    readonly_fields = ['created_at', 'updated_at', 'emi']
    
    fieldsets = (
        ('Applicant Details', {
            'fields': ('role', 'full_name', 'username', 'mobile', 'email', 'gender')
        }),
        ('Address Information', {
            'fields': ('city', 'state', 'pin_code')
        }),
        ('Loan Details', {
            'fields': ('loan_type', 'loan_amount', 'tenure_months', 'interest_rate', 'emi', 'loan_purpose')
        }),
        ('Bank Details', {
            'fields': ('bank_name', 'bank_type', 'account_number', 'ifsc_code')
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(LoanApplication)
class LoanApplicationAdmin(admin.ModelAdmin):
    list_display = ['applicant', 'status', 'assigned_agent', 'assigned_employee', 'created_at']
    list_filter = ['status', 'created_at']
    search_fields = ['applicant__full_name', 'applicant__mobile']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(ApplicantDocument)
class ApplicantDocumentAdmin(admin.ModelAdmin):
    list_display = ['loan_application', 'document_type', 'is_required', 'uploaded_at']
    list_filter = ['document_type', 'is_required', 'uploaded_at']
    search_fields = ['loan_application__applicant__full_name']
    readonly_fields = ['uploaded_at']


@admin.register(Loan)
class LoanAdmin(admin.ModelAdmin):
    list_display = ['full_name', 'mobile_number', 'loan_type', 'loan_amount', 'status', 'assigned_agent', 'created_at']
    list_filter = ['status', 'loan_type', 'created_at']
    search_fields = ['full_name', 'mobile_number', 'bank_name']
    readonly_fields = ['user_id', 'emi', 'created_at', 'updated_at']


@admin.register(Complaint)
class ComplaintAdmin(admin.ModelAdmin):
    list_display = ['complaint_id', 'customer_name', 'complaint_type', 'priority', 'status', 'filed_by_employee', 'filed_by_agent', 'assigned_admin', 'created_at']
    list_filter = ['status', 'priority', 'complaint_type', 'created_at']
    search_fields = ['complaint_id', 'customer_name']
    readonly_fields = ['complaint_id', 'created_at', 'updated_at']
    
    fieldsets = (
        ('Complaint Details', {
            'fields': ('complaint_id', 'customer_name', 'complaint_type', 'description')
        }),
        ('Related Information', {
            'fields': ('loan', 'filed_by_employee', 'filed_by_agent')
        }),
        ('Status & Priority', {
            'fields': ('status', 'priority', 'assigned_admin')
        }),
        ('Resolution', {
            'fields': ('resolved_at',),
            'classes': ('collapse',)
        }),
        ('Metadata', {
            'fields': ('created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(ComplaintComment)
class ComplaintCommentAdmin(admin.ModelAdmin):
    list_display = ['complaint', 'commented_by', 'created_at']
    list_filter = ['created_at']
    readonly_fields = ['created_at']


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ['action', 'user', 'created_at']
    list_filter = ['action', 'created_at']
    readonly_fields = ['created_at']



