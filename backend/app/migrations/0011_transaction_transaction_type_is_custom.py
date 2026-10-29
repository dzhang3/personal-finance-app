from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0010_syncjob_lease_expires_at_alter_syncattempt_outcome'),
    ]

    operations = [
        migrations.AddField(
            model_name='transaction',
            name='transaction_type_is_custom',
            field=models.BooleanField(default=False),
        ),
    ]
