# Generated manually for official loan_id field

from django.db import migrations, models


def copy_user_id_to_loan_id(apps, schema_editor):
    Loan = apps.get_model('core', 'Loan')
    for loan in Loan.objects.exclude(user_id__isnull=True).exclude(user_id=''):
        raw = str(loan.user_id or '').strip().upper()
        if not raw:
            continue
        if raw.startswith('LOAN-') and raw[5:].isdigit():
            continue
        if raw.startswith('APP-') and raw[4:].isdigit():
            continue
        if not loan.loan_id:
            loan.loan_id = raw
            loan.save(update_fields=['loan_id'])


def sync_application_loan_ids(apps, schema_editor):
    Loan = apps.get_model('core', 'Loan')
    LoanApplication = apps.get_model('core', 'LoanApplication')
    for app in LoanApplication.objects.select_related('applicant').all():
        if app.loan_id:
            continue
        applicant = app.applicant
        if not applicant:
            continue
        legacy = Loan.objects.filter(
            mobile_number=applicant.mobile,
            full_name=applicant.full_name,
        ).exclude(loan_id__isnull=True).exclude(loan_id='').order_by('-updated_at').first()
        if legacy and legacy.loan_id:
            app.loan_id = legacy.loan_id
            app.save(update_fields=['loan_id'])


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0034_business_name_field'),
    ]

    operations = [
        migrations.AddField(
            model_name='loan',
            name='loan_id',
            field=models.CharField(
                blank=True,
                help_text='Official manual Loan ID assigned during bank processing',
                max_length=50,
                null=True,
                unique=True,
            ),
        ),
        migrations.AddField(
            model_name='loanapplication',
            name='loan_id',
            field=models.CharField(
                blank=True,
                help_text='Official manual Loan ID (synced with linked legacy loan)',
                max_length=50,
                null=True,
            ),
        ),
        migrations.RunPython(copy_user_id_to_loan_id, migrations.RunPython.noop),
        migrations.RunPython(sync_application_loan_ids, migrations.RunPython.noop),
    ]
