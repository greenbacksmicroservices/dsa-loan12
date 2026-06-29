from django.db import migrations, models
from django.utils import timezone


def backfill_banking_started_at(apps, schema_editor):
  LoanApplication = apps.get_model('core', 'LoanApplication')
  Loan = apps.get_model('core', 'Loan')

  for app in LoanApplication.objects.filter(status='Required Follow-up'):
    if app.banking_processing_started_at:
      continue
    anchor = app.follow_up_scheduled_at or app.follow_up_notified_at
    if anchor:
      LoanApplication.objects.filter(pk=app.pk).update(banking_processing_started_at=anchor)

  for loan in Loan.objects.filter(status='follow_up'):
    if loan.banking_processing_started_at:
      continue
    anchor = loan.follow_up_triggered_at or loan.action_taken_at
    if anchor:
      Loan.objects.filter(pk=loan.pk).update(banking_processing_started_at=anchor)


class Migration(migrations.Migration):

  dependencies = [
    ('core', '0035_official_loan_id_field'),
  ]

  operations = [
    migrations.AddField(
      model_name='loanapplication',
      name='banking_processing_started_at',
      field=models.DateTimeField(
        blank=True,
        help_text='When the application entered Banking Login Process',
        null=True,
      ),
    ),
    migrations.AddField(
      model_name='loan',
      name='banking_processing_started_at',
      field=models.DateTimeField(
        blank=True,
        help_text='When the application entered Banking Login Process',
        null=True,
      ),
    ),
    migrations.RunPython(backfill_banking_started_at, migrations.RunPython.noop),
  ]
