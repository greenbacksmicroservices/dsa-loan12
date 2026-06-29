from datetime import timedelta

from django.db import migrations, models
import django.db.models.deletion


def _backfill_legacy_loan_links(apps, schema_editor):
    Loan = apps.get_model('core', 'Loan')
    LoanApplication = apps.get_model('core', 'LoanApplication')

    for app in LoanApplication.objects.filter(legacy_loan__isnull=True).select_related('applicant').iterator():
        applicant = getattr(app, 'applicant', None)
        if not applicant:
            continue

        created_at = app.created_at
        window_start = created_at - timedelta(days=7)
        window_end = created_at + timedelta(days=7)
        base_qs = Loan.objects.filter(created_at__gte=window_start, created_at__lte=window_end)
        if app.assigned_agent_id:
            base_qs = base_qs.filter(assigned_agent_id=app.assigned_agent_id)

        strict_filters = []
        if applicant.email and applicant.mobile:
            strict_filters.append({
                'email__iexact': applicant.email,
                'mobile_number': applicant.mobile,
            })
        if applicant.full_name and applicant.mobile:
            strict_filters.append({
                'full_name__iexact': applicant.full_name,
                'mobile_number': applicant.mobile,
            })
        if applicant.email and applicant.full_name:
            strict_filters.append({
                'email__iexact': applicant.email,
                'full_name__iexact': applicant.full_name,
            })
        if applicant.username:
            strict_filters.append({
                'username__iexact': applicant.username,
            })

        match = None
        for filters in strict_filters:
            candidate = base_qs.filter(**filters).order_by('created_at').first()
            if candidate:
                match = candidate
                break

        if not match:
            continue

        if LoanApplication.objects.filter(legacy_loan_id=match.id).exclude(pk=app.pk).exists():
            continue

        app.legacy_loan_id = match.id
        app.save(update_fields=['legacy_loan_id'])


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0036_banking_processing_started_at'),
    ]

    operations = [
        migrations.AddField(
            model_name='loanapplication',
            name='legacy_loan',
            field=models.OneToOneField(
                blank=True,
                help_text='Explicit paired legacy Loan record for this workflow application',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='workflow_application',
                to='core.loan',
            ),
        ),
        migrations.RunPython(_backfill_legacy_loan_links, migrations.RunPython.noop),
    ]
