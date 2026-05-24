from django.db import models
from drama.models import Movie
from users.models import Profile # O'zingizning Profile manzilingizni to'g'rilab yozing

class FundingProject(models.Model):
    STATUS_CHOICES = (
        ('funding', 'Pul yig\'ilmoqda'),
        ('translating', 'Tarjima jarayonida'),
        ('released', 'Saytga chiqdi (Tayyor)'),
    )
    
    movie = models.OneToOneField(Movie, on_delete=models.CASCADE, related_name='funding_project')
    target_amount = models.PositiveIntegerField(verbose_name="Yig'ilishi kerak bo'lgan jami Coin")
    collected_amount = models.PositiveIntegerField(default=0, verbose_name="Hozirgacha yig'ildi")
    min_fund_amount = models.PositiveIntegerField(default=50, verbose_name="Minimal hissa (Coin)")
    post_release_price = models.PositiveIntegerField(default=100, verbose_name="Tayyor serial narxi (Coin)")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='funding')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.movie.title} - {self.get_status_display()}"

    @property
    def progress_percentage(self):
        if self.target_amount == 0: return 0
        calc = (self.collected_amount / self.target_amount) * 100
        return min(calc, 100)

    def has_access(self, profile):
        return self.contributors.filter(profile=profile).exists()

class FundingContributor(models.Model):
    project = models.ForeignKey(FundingProject, on_delete=models.CASCADE, related_name='contributors')
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE)
    amount_paid = models.PositiveIntegerField()
    funded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-funded_at']

    def __str__(self):
        return f"{self.profile.user.username} -> {self.amount_paid} Coin"