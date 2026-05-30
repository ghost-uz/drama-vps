from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0008_remove_profile_followers_alter_profile_following'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='CryptoTopUpRequest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('amount_usdt', models.DecimalField(decimal_places=2, max_digits=10, verbose_name="To'lov summasi (USDT)")),
                ('points', models.PositiveIntegerField(blank=True, null=True, verbose_name='Beriladigan Coinlar')),
                ('receipt_image', models.ImageField(upload_to='crypto_receipts/%Y/%m/', verbose_name="To'lov skrinshotı")),
                ('status', models.CharField(choices=[('pending', 'Kutilmoqda'), ('approved', 'Tasdiqlandi'), ('rejected', 'Rad etildi')], default='pending', max_length=15, verbose_name='Holati')),
                ('admin_note', models.TextField(blank=True, null=True, verbose_name='Admin izohi (rad etilsa)')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='crypto_topup_requests', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': "Kripto to'ldirish so'rovi",
                'verbose_name_plural': "Kripto to'ldirish so'rovlari",
                'ordering': ['-created_at'],
            },
        ),
    ]
