from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0011_transaction_transaction_type_is_custom'),
    ]

    operations = [
        migrations.CreateModel(
            name='BudgetTarget',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('category', models.CharField(blank=True, default='', max_length=50)),
                ('monthly_limit', models.DecimalField(decimal_places=2, max_digits=12)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='budget_targets', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'constraints': [
                    models.UniqueConstraint(fields=('user', 'category'), name='unique_budget_target_per_user_category'),
                ],
            },
        ),
    ]
