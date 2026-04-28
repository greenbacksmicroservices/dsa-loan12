from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0026_alter_user_role"),
    ]

    operations = [
        migrations.AddField(
            model_name="applicant",
            name="current_job_title",
            field=models.CharField(blank=True, max_length=150, null=True),
        ),
        migrations.AddField(
            model_name="applicant",
            name="current_salary",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True),
        ),
        migrations.AddField(
            model_name="applicant",
            name="expected_salary",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True),
        ),
        migrations.AddField(
            model_name="applicant",
            name="notice_period",
            field=models.CharField(blank=True, max_length=120, null=True),
        ),
        migrations.AddField(
            model_name="applicant",
            name="total_experience_years",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True),
        ),
    ]
