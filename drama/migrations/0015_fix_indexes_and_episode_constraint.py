from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('drama', '0014_actorgift'),
    ]

    operations = [
        # Episode: bir serialda bir xil qism raqami bo'lishini oldini olish
        migrations.AlterUniqueTogether(
            name='episode',
            unique_together={('movie', 'episode_number')},
        ),

        # Episode: default ordering
        migrations.AlterModelOptions(
            name='episode',
            options={
                'ordering': ['episode_number'],
                'verbose_name': 'Qism',
                'verbose_name_plural': 'Qismlar',
            },
        ),

        # Movie: is_draft filtri uchun DB index
        migrations.AddIndex(
            model_name='movie',
            index=models.Index(fields=['is_draft'], name='drama_movie_is_draf_idx'),
        ),

        # Movie: is_draft + created_at birgalikda (MoviesView queryset uchun)
        migrations.AddIndex(
            model_name='movie',
            index=models.Index(fields=['is_draft', '-created_at'], name='drama_movie_is_draf_ct_idx'),
        ),
    ]
