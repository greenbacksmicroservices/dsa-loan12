from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import Agent, Loan, Complaint, ComplaintComment, ActivityLog, LoanDocument, ApplicantDocument, Applicant, LoanApplication

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'role', 'phone', 'first_name', 'last_name', 'is_active']
        read_only_fields = ['id']


class AgentSerializer(serializers.ModelSerializer):
    total_leads = serializers.ReadOnlyField()
    approved_loans_count = serializers.ReadOnlyField()
    total_disbursed_amount = serializers.ReadOnlyField()
    commission = serializers.ReadOnlyField()
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True)
    
    class Meta:
        model = Agent
        fields = '__all__'
        read_only_fields = ['created_at', 'updated_at']


class LoanSerializer(serializers.ModelSerializer):
    assigned_agent_name = serializers.CharField(source='assigned_agent.name', read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    
    class Meta:
        model = Loan
        fields = '__all__'
        read_only_fields = ['created_at', 'updated_at']


class LoanDocumentSerializer(serializers.ModelSerializer):
    document_type_display = serializers.CharField(source='get_document_type_display', read_only=True)
    
    class Meta:
        model = LoanDocument
        fields = '__all__'
        read_only_fields = ['uploaded_at', 'updated_at']


class ComplaintCommentSerializer(serializers.ModelSerializer):
    commented_by_name = serializers.CharField(source='commented_by.username', read_only=True)
    
    class Meta:
        model = ComplaintComment
        fields = '__all__'
        read_only_fields = ['created_at']


class ComplaintSerializer(serializers.ModelSerializer):
    loan_details = LoanSerializer(source='loan', read_only=True)
    assigned_admin_name = serializers.CharField(source='assigned_admin.username', read_only=True)
    filed_by_employee_name = serializers.CharField(source='filed_by_employee.get_full_name', read_only=True)
    filed_by_agent_name = serializers.CharField(source='filed_by_agent.name', read_only=True)
    comments = ComplaintCommentSerializer(many=True, read_only=True)
    
    class Meta:
        model = Complaint
        fields = '__all__'
        read_only_fields = ['complaint_id', 'created_at', 'updated_at']


class ActivityLogSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source='user.username', read_only=True)
    
    class Meta:
        model = ActivityLog
        fields = '__all__'
        read_only_fields = ['created_at']


class ApplicantSerializer(serializers.ModelSerializer):
    """Serializer for Applicant model"""
    class Meta:
        model = Applicant
        fields = '__all__'
        read_only_fields = ['created_at', 'updated_at']


class LoanApplicationSerializer(serializers.ModelSerializer):
    """Serializer for Loan Application with assignment tracking"""
    applicant_name = serializers.CharField(source='applicant.full_name', read_only=True)
    applicant_email = serializers.CharField(source='applicant.email', read_only=True)
    applicant_phone = serializers.CharField(source='applicant.mobile', read_only=True)
    assigned_employee_name = serializers.CharField(source='assigned_employee.get_full_name', read_only=True)
    assigned_agent_name = serializers.CharField(source='assigned_agent.name', read_only=True, allow_null=True)
    assigned_by_name = serializers.CharField(source='assigned_by.username', read_only=True, allow_null=True)
    
    class Meta:
        model = LoanApplication
        fields = '__all__'
        read_only_fields = ['created_at', 'updated_at', 'assigned_at', 'approved_at', 'rejected_at']


class DashboardStatsSerializer(serializers.Serializer):
    """Serializer for Dashboard Statistics"""
    total_new_entry = serializers.IntegerField()
    waiting_for_processing = serializers.IntegerField()
    required_follow_up = serializers.IntegerField()
    approved = serializers.IntegerField()
    rejected = serializers.IntegerField()
    disbursed = serializers.IntegerField()
    
    # Chart data
    loan_status_breakdown = serializers.DictField()
    monthly_loan_trend = serializers.ListField()
    
    # Complaints overview
    total_complaints = serializers.IntegerField()
    open_complaints = serializers.IntegerField()
    resolved_complaints = serializers.IntegerField()
    
    # Recent activities
    recent_activities = ActivityLogSerializer(many=True)


class ApplicantDocumentSerializer(serializers.ModelSerializer):
    document_type_display = serializers.CharField(source='get_document_type_display', read_only=True)
    file_url = serializers.SerializerMethodField()
    
    class Meta:
        model = ApplicantDocument
        fields = ['id', 'loan_application', 'document_type', 'document_type_display', 'file', 'file_url', 'is_required', 'uploaded_at']
        read_only_fields = ['uploaded_at']
    
    def get_file_url(self, obj):
        request = self.context.get('request')
        if obj.file and request:
            return request.build_absolute_uri(obj.file.url)
        return None

class ApplicantSerializer(serializers.ModelSerializer):
    """Serializer for Applicant Model"""
    class Meta:
        model = Applicant
        fields = '__all__'
        read_only_fields = ['created_at', 'updated_at']


class LoanApplicationSerializer(serializers.ModelSerializer):
    """Serializer for LoanApplication with related details"""
    applicant_details = ApplicantSerializer(source='applicant', read_only=True)
    assigned_agent_name = serializers.CharField(source='assigned_agent.name', read_only=True)
    assigned_employee_name = serializers.SerializerMethodField()
    assigned_by_name = serializers.CharField(source='assigned_by.get_full_name', read_only=True)
    approved_by_name = serializers.CharField(source='approved_by.get_full_name', read_only=True)
    
    class Meta:
        model = LoanApplication
        fields = [
            'id', 'applicant', 'applicant_details', 'status',
            'assigned_agent', 'assigned_agent_name',
            'assigned_employee', 'assigned_employee_name',
            'assigned_at', 'assigned_by', 'assigned_by_name',
            'approved_by', 'approved_by_name',
            'approval_notes', 'approved_at',
            'rejected_by', 'rejection_reason', 'rejected_at',
            'follow_up_scheduled_at', 'follow_up_notified_at',
            'follow_up_count', 'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']
    
    def get_assigned_employee_name(self, obj):
        if obj.assigned_employee:
            return obj.assigned_employee.get_full_name()
        return None