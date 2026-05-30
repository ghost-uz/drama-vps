from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm
from .models import Profile, TopUpRequest, CryptoTopUpRequest
from django.forms.widgets import SelectDateWidget # 🌟 YANIGI QO'SHILDI
from datetime import datetime # 🌟 YANIGI QO'SHILDI
# Hozirgi yildan 1980 gacha bo'lgan yillar ro'yxatini yaratamiz
current_year = datetime.now().year
YEARS = [x for x in range(current_year, 1979, -1)]

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
            # 🌟 O'ZGARTIRILGAN QISM
            'birth_date': SelectDateWidget(
                years=YEARS,
                empty_label=("Yil", "Oy", "Kun"), # Tanlanmagan holatdagi yozuv
                attrs={
                    # Uchala quti uchun umumiy CSS klass (settings.html da buni to'g'rilaymiz)
                    'class': 'custom-date-select outline-none focus:border-[#00cc4c] transition-colors cursor-pointer',
                }
            ),
            'bio': forms.Textarea(attrs={'placeholder': 'O\'zingiz haqingizda qisqacha...', 'rows': 3}),
            'telegram_id': forms.TextInput(attrs={'placeholder': '@username'}),
        }
        
# YANGA QO'SHILGAN FORMA
class TopUpRequestForm(forms.ModelForm):
    class Meta:
        model = TopUpRequest
        fields = ['amount_uzs', 'receipt_image']
        labels = {
            'amount_uzs': "To'lov summasi (UZS)",
            'receipt_image': "Chek rasmini yuklang"
        }
        widgets = {
            'amount_uzs': forms.NumberInput(
                attrs={
                    'placeholder': 'Masalan: 10000',
                    'min': '1000', # Eng kamida 1000 so'm
                    'class': 'w-full bg-white/5 border border-white/10 rounded-2xl p-4 text-white outline-none focus:border-[#00cc4c] transition-colors',
                }
            ),
            'receipt_image': forms.FileInput(
                attrs={
                    'class': 'w-full bg-white/5 border border-white/10 rounded-2xl p-3 text-gray-400 outline-none focus:border-[#00cc4c] file:mr-4 file:py-2.5 file:px-6 file:rounded-xl file:border-0 file:text-sm file:font-black file:bg-[#00cc4c] file:text-black hover:file:bg-[#00ff62] transition-colors cursor-pointer',
                    'accept': 'image/*'
                }
            ),
        }


class CryptoTopUpRequestForm(forms.ModelForm):
    class Meta:
        model = CryptoTopUpRequest
        fields = ['amount_usdt', 'receipt_image']
        labels = {
            'amount_usdt': "To'lov summasi (USDT)",
            'receipt_image': "To'lov skrinshotini yuklang",
        }
        widgets = {
            'amount_usdt': forms.NumberInput(
                attrs={
                    'placeholder': 'Masalan: 5.00',
                    'min': '1',
                    'step': '0.01',
                    'class': 'w-full bg-white/5 border border-white/10 rounded-2xl p-4 text-white outline-none focus:border-[#0098EA] transition-colors',
                }
            ),
            'receipt_image': forms.FileInput(
                attrs={
                    'class': 'w-full bg-white/5 border border-white/10 rounded-2xl p-3 text-gray-400 outline-none focus:border-[#0098EA] file:mr-4 file:py-2.5 file:px-6 file:rounded-xl file:border-0 file:text-sm file:font-black file:bg-[#0098EA] file:text-white hover:file:bg-[#007bc2] transition-colors cursor-pointer',
                    'accept': 'image/*',
                }
            ),
        }