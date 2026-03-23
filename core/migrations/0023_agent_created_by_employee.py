# Generated migration for adding created_by_employee field to Agent model

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0022_useronboardingprofile_useronboardingdocument'),
    ]

    operations = [
        migrations.AddField(
            model_name='agent',
            name='created_by_employee',
            field=models.ForeignKey(
                blank=True,
                help_text='Employee who created this agent',
                limit_choices_to={'role': 'employee'},
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='employee_created_agents',
                to=settings.AUTH_USER_MODEL
            ),
        ),
    ]
