from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm
from .models import Profile

class UserRegisterForm(UserCreationForm):
    email = forms.EmailField()

    class Meta:
        model = User
        fields = ['username', 'email']

class UserUpdateForm(forms.ModelForm):
    email = forms.EmailField()

    class Meta:
        model = User
        fields = ['username', 'email']

class ProfileUpdateForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = ['avatar', 'bio', 'birth_date', 'telegram_id']
        widgets = {
            'birth_date': forms.DateInput(
                attrs={
                    'placeholder': 'DD/MM/YYYY', # Siz xohlagan placeholder
                    'class': 'w-full bg-white/5 border border-white/10 rounded-2xl p-4 text-white outline-none focus:border-[#00cc4c]', # Styling uchun
                }
            ),
            'bio': forms.Textarea(attrs={'placeholder': 'O\'zingiz haqingizda qisqacha...', 'rows': 3}),
            'telegram_id': forms.TextInput(attrs={'placeholder': '@username'}),
        }