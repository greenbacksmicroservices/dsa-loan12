from django import forms
from django.core.validators import FileExtensionValidator

from .models import Applicant, ApplicantDocument, User


class ApplicantStep1Form(forms.ModelForm):
    """Step 1 (Channel Partner): Basic applicant details."""

    username = forms.CharField(
        required=True,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Enter Username",
                "required": True,
            }
        ),
    )

    class Meta:
        model = Applicant
        fields = [
            "full_name",
            "username",
            "mobile",
            "email",
            "city",
            "state",
            "pin_code",
            "gender",
        ]
        widgets = {
            "full_name": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Enter Full Name",
                    "required": True,
                }
            ),
            "mobile": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "+91 XXXXX XXXXX",
                    "required": True,
                }
            ),
            "email": forms.EmailInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "example@mail.com",
                    "required": True,
                }
            ),
            "city": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Enter City",
                    "required": True,
                }
            ),
            "state": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Enter State",
                    "required": True,
                }
            ),
            "pin_code": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "XXXXXX",
                    "required": True,
                }
            ),
            "gender": forms.Select(
                attrs={
                    "class": "form-control",
                    "required": True,
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["gender"].choices = [("", "Select Gender"), *Applicant.GENDER_CHOICES]

    def clean_username(self):
        username = (self.cleaned_data.get("username") or "").strip()
        if not username:
            raise forms.ValidationError("Username is required.")
        if Applicant.objects.filter(username=username).exists():
            raise forms.ValidationError("This username is already taken.")
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError("This username is already in use.")
        return username

    def clean_email(self):
        email = self.cleaned_data.get("email")
        if Applicant.objects.filter(email=email).exists():
            raise forms.ValidationError("This email is already registered.")
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("This email is already in use.")
        return email

    def clean_mobile(self):
        mobile = (self.cleaned_data.get("mobile") or "").strip()
        digits_only = "".join(ch for ch in mobile if ch.isdigit())
        if len(digits_only) < 10:
            raise forms.ValidationError("Please enter a valid mobile number.")
        return mobile

    def clean_pin_code(self):
        pin_code = (self.cleaned_data.get("pin_code") or "").strip()
        digits_only = "".join(ch for ch in pin_code if ch.isdigit())
        if len(digits_only) != 6:
            raise forms.ValidationError("Please enter a valid 6-digit pin code.")
        return pin_code


class EmployeeRegistrationStep1Form(forms.ModelForm):
    """Step 1 (Employee): Basic + professional details."""

    class Meta:
        model = Applicant
        fields = [
            "full_name",
            "mobile",
            "email",
            "city",
            "state",
            "pin_code",
            "gender",
            "current_job_title",
            "total_experience_years",
            "current_salary",
            "expected_salary",
            "notice_period",
        ]
        widgets = {
            "full_name": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Enter Name",
                    "required": True,
                }
            ),
            "mobile": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Enter Phone Number",
                    "required": True,
                }
            ),
            "email": forms.EmailInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Enter Gmail",
                    "required": True,
                }
            ),
            "city": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Enter City",
                    "required": True,
                }
            ),
            "state": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Enter State",
                    "required": True,
                }
            ),
            "pin_code": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Enter Pin",
                    "required": True,
                }
            ),
            "gender": forms.Select(
                attrs={
                    "class": "form-control",
                    "required": True,
                }
            ),
            "current_job_title": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Current Job Title",
                }
            ),
            "total_experience_years": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Total Experience (years)",
                    "step": "0.1",
                    "min": "0",
                }
            ),
            "current_salary": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Current Salary",
                    "step": "0.01",
                    "min": "0",
                }
            ),
            "expected_salary": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Expected Salary",
                    "step": "0.01",
                    "min": "0",
                }
            ),
            "notice_period": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Notice Period",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["gender"].choices = [("", "Select Gender"), *Applicant.GENDER_CHOICES]

    def clean_email(self):
        email = self.cleaned_data.get("email")
        if Applicant.objects.filter(email=email).exists():
            raise forms.ValidationError("This email is already registered.")
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("This email is already in use.")
        return email

    def clean_mobile(self):
        mobile = (self.cleaned_data.get("mobile") or "").strip()
        digits_only = "".join(ch for ch in mobile if ch.isdigit())
        if len(digits_only) < 10:
            raise forms.ValidationError("Please enter a valid mobile number.")
        return mobile

    def clean_pin_code(self):
        pin_code = (self.cleaned_data.get("pin_code") or "").strip()
        digits_only = "".join(ch for ch in pin_code if ch.isdigit())
        if len(digits_only) != 6:
            raise forms.ValidationError("Please enter a valid 6-digit pin code.")
        return pin_code

class ApplicantStep2Form(forms.Form):
    """Step 2: Bank details."""

    BANK_TYPE_CHOICES = [
        ("", "Select Bank Type"),
        ("current", "Current"),
        ("saving", "Saving"),
        ("cc", "CC"),
        ("od", "OD"),
    ]

    bank_name = forms.CharField(
        required=True,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Enter Bank Name",
                "required": True,
            }
        ),
    )
    bank_account_number = forms.CharField(
        required=True,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Enter Bank Account No",
                "required": True,
            }
        ),
    )
    ifsc_code = forms.CharField(
        required=True,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Enter IFSC No",
                "required": True,
            }
        ),
    )
    bank_type = forms.ChoiceField(
        required=True,
        choices=BANK_TYPE_CHOICES,
        widget=forms.Select(
            attrs={
                "class": "form-control",
                "required": True,
            }
        ),
    )

    def clean_bank_account_number(self):
        account_number = (self.cleaned_data.get("bank_account_number") or "").replace(" ", "")
        if not account_number:
            raise forms.ValidationError("Bank account number is required.")
        return account_number

    def clean_ifsc_code(self):
        ifsc_code = (self.cleaned_data.get("ifsc_code") or "").strip().upper()
        if len(ifsc_code) < 8:
            raise forms.ValidationError("Please enter a valid IFSC code.")
        return ifsc_code


class ApplicantDocumentForm(forms.ModelForm):
    """Single document upload model form (legacy helper)."""

    class Meta:
        model = ApplicantDocument
        fields = ["document_type", "file"]
        widgets = {
            "document_type": forms.Select(
                attrs={
                    "class": "form-control",
                    "required": True,
                }
            ),
            "file": forms.FileInput(
                attrs={
                    "class": "form-control",
                    "accept": ".pdf,.doc,.docx,.jpg,.jpeg,.png",
                    "required": True,
                }
            ),
        }


class DocumentUploadForm(forms.Form):
    """Step 3: Mandatory document uploads."""

    photo = forms.FileField(
        label="Photo",
        required=True,
        validators=[FileExtensionValidator(allowed_extensions=["jpg", "jpeg", "png"])],
    )
    pan_card = forms.FileField(
        label="PAN Card",
        required=True,
        validators=[FileExtensionValidator(allowed_extensions=["pdf", "jpg", "jpeg", "png"])],
    )
    aadhaar_card = forms.FileField(
        label="Aadhaar Card",
        required=True,
        validators=[FileExtensionValidator(allowed_extensions=["pdf", "jpg", "jpeg", "png"])],
    )

    def __init__(self, *args, **kwargs):
        kwargs.pop("role", None)  # Backward compatibility with existing view call.
        super().__init__(*args, **kwargs)
        self.fields["photo"].widget.attrs.update(
            {
                "class": "form-control",
                "accept": ".jpg,.jpeg,.png,image/jpeg,image/png",
            }
        )
        self.fields["pan_card"].widget.attrs.update(
            {
                "class": "form-control",
                "accept": ".pdf,.jpg,.jpeg,.png,image/jpeg,image/png,application/pdf",
            }
        )
        self.fields["aadhaar_card"].widget.attrs.update(
            {
                "class": "form-control",
                "accept": ".pdf,.jpg,.jpeg,.png,image/jpeg,image/png,application/pdf",
            }
        )

    def clean(self):
        cleaned_data = super().clean()
        max_size = 5 * 1024 * 1024
        for key in ("photo", "pan_card", "aadhaar_card"):
            uploaded_file = cleaned_data.get(key)
            if uploaded_file and uploaded_file.size > max_size:
                self.add_error(key, "Each file must be 5 MB or less.")
        return cleaned_data


class EmployeeResumeUploadForm(forms.Form):
    """Step 2 (Employee): Resume upload only."""

    resume = forms.FileField(
        label="Upload Resume",
        required=True,
        validators=[FileExtensionValidator(allowed_extensions=["pdf", "doc", "docx"])],
        widget=forms.FileInput(
            attrs={
                "class": "form-control",
                "accept": ".pdf,.doc,.docx",
                "required": True,
            }
        ),
    )

    def clean_resume(self):
        resume = self.cleaned_data.get("resume")
        if not resume:
            return resume
        max_size = 3 * 1024 * 1024
        if resume.size > max_size:
            raise forms.ValidationError("Resume size must be 3 MB or less.")
        return resume
