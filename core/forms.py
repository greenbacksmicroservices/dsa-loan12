from django import forms
from django.core.validators import FileExtensionValidator
from .models import Applicant, LoanApplication, ApplicantDocument
import os


class ApplicantStep1Form(forms.ModelForm):
    """Step 1: Applicant Details"""
    
    class Meta:
        model = Applicant
        fields = ['role', 'full_name', 'username', 'mobile', 'email', 'city', 'state', 'pin_code', 'gender']
        widgets = {
            'role': forms.RadioSelect(choices=Applicant.ROLE_CHOICES),
            'full_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter Full Name',
                'required': True
            }),
            'username': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Choose Username',
                'required': True
            }),
            'mobile': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '+91 XXXXX XXXXX',
                'pattern': r'^\+?1?\d{9,15}$',
                'required': True
            }),
            'email': forms.EmailInput(attrs={
                'class': 'form-control',
                'placeholder': 'example@mail.com',
                'required': True
            }),
            'city': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter City',
                'required': True
            }),
            'state': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter State',
                'required': True
            }),
            'pin_code': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'XXXXXX',
                'required': True
            }),
            'gender': forms.Select(attrs={
                'class': 'form-control',
                'required': True
            }),
        }
    
    def clean_username(self):
        username = self.cleaned_data.get('username')
        if Applicant.objects.filter(username=username).exists():
            raise forms.ValidationError("This username is already taken.")
        return username
    
    def clean_email(self):
        email = self.cleaned_data.get('email')
        if Applicant.objects.filter(email=email).exists():
            raise forms.ValidationError("This email is already registered.")
        return email


class ApplicantStep2Form(forms.ModelForm):
    """Step 2: Loan & Bank Details"""
    
    class Meta:
        model = Applicant
        fields = ['loan_type', 'loan_amount', 'tenure_months', 'interest_rate', 'loan_purpose', 
                  'bank_name', 'bank_type', 'account_number', 'ifsc_code']
        widgets = {
            'loan_type': forms.Select(attrs={
                'class': 'form-control',
                'required': True
            }),
            'loan_amount': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter Loan Amount (₹)',
                'step': '0.01',
                'required': True
            }),
            'tenure_months': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter Tenure (in months)',
                'min': '1',
                'required': True
            }),
            'interest_rate': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter Interest Rate (%)',
                'step': '0.01',
                'required': True
            }),
            'loan_purpose': forms.Textarea(attrs={
                'class': 'form-control',
                'placeholder': 'Enter Loan Purpose',
                'rows': 3,
                'required': True
            }),
            'bank_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter Bank Name',
                'required': True
            }),
            'bank_type': forms.Select(attrs={
                'class': 'form-control',
                'required': True
            }),
            'account_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter Bank Account Number',
                'required': True
            }),
            'ifsc_code': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter IFSC Code',
                'required': True
            }),
        }


class ApplicantDocumentForm(forms.ModelForm):
    """Step 3: Document Upload"""
    
    class Meta:
        model = ApplicantDocument
        fields = ['document_type', 'file']
        widgets = {
            'document_type': forms.Select(attrs={
                'class': 'form-control',
                'required': True
            }),
            'file': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*,.pdf',
                'required': True
            }),
        }


class DocumentUploadForm(forms.Form):
    """Bulk Document Upload Form"""
    
    photo = forms.FileField(
        label="Applicant Photo (JPG/PNG)",
        required=True,
        validators=[FileExtensionValidator(allowed_extensions=['jpg', 'jpeg', 'png', 'gif'])]
    )
    
    pan_front = forms.FileField(
        label="PAN Card Front (JPG/PNG)",
        required=True,
        validators=[FileExtensionValidator(allowed_extensions=['jpg', 'jpeg', 'png', 'gif'])]
    )
    
    pan_back = forms.FileField(
        label="PAN Card Back (JPG/PNG)",
        required=True,
        validators=[FileExtensionValidator(allowed_extensions=['jpg', 'jpeg', 'png', 'gif'])]
    )
    
    aadhaar_front = forms.FileField(
        label="Aadhaar Front (JPG/PNG)",
        required=True,
        validators=[FileExtensionValidator(allowed_extensions=['jpg', 'jpeg', 'png', 'gif'])]
    )
    
    aadhaar_back = forms.FileField(
        label="Aadhaar Back (JPG/PNG)",
        required=True,
        validators=[FileExtensionValidator(allowed_extensions=['jpg', 'jpeg', 'png', 'gif'])]
    )
    
    permanent_address = forms.FileField(
        label="Permanent Address Proof (PDF/JPG/PNG)",
        required=True,
        validators=[FileExtensionValidator(allowed_extensions=['pdf', 'jpg', 'jpeg', 'png', 'gif'])]
    )
    
    current_address = forms.FileField(
        label="Current Address Proof (PDF/JPG/PNG)",
        required=False,
        validators=[FileExtensionValidator(allowed_extensions=['pdf', 'jpg', 'jpeg', 'png', 'gif'])]
    )
    
    salary_slip = forms.FileField(
        label="Salary Slip (PDF/JPG/PNG)",
        required=False,
        validators=[FileExtensionValidator(allowed_extensions=['pdf', 'jpg', 'jpeg', 'png', 'gif'])]
    )
    
    bank_statement = forms.FileField(
        label="Bank Statement (PDF)",
        required=False,
        validators=[FileExtensionValidator(allowed_extensions=['pdf'])]
    )
    
    form_16 = forms.FileField(
        label="Form 16 (PDF)",
        required=False,
        validators=[FileExtensionValidator(allowed_extensions=['pdf', 'jpg', 'jpeg', 'png', 'gif'])]
    )
    
    service_book = forms.FileField(
        label="Service Book (PDF/JPG/PNG)",
        required=False,
        validators=[FileExtensionValidator(allowed_extensions=['pdf', 'jpg', 'jpeg', 'png', 'gif'])]
    )
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({
                'class': 'form-control',
                'accept': '.pdf,.jpg,.jpeg,.png,.gif'
            })
