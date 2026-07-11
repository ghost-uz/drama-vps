from datetime import datetime  # 🌟 YANIGI QO'SHILDI

from django import forms
from django.contrib.auth.forms import PasswordResetForm, UserCreationForm
from django.contrib.auth.models import User
from django.forms.widgets import SelectDateWidget  # 🌟 YANIGI QO'SHILDI
from django.template import loader

from core.tasks import send_email_task

from .models import CryptoTopUpRequest, Profile, TopUpRequest

# Hozirgi yildan 1980 gacha bo'lgan yillar ro'yxatini yaratamiz
current_year = datetime.now().year
YEARS = list(range(current_year, 1979, -1))


class UserRegisterForm(UserCreationForm):
    email = forms.EmailField()

    class Meta:
        model = User
        fields = ["username", "email"]

    def clean_email(self):
        """Email unikal [P6-T1] — tasdiqlash va parol tiklash aniq bitta hisobga borishi uchun.

        Forma darajasida (DB constraint emas): legacy dublikatlar migratsiyani
        yiqitmasligi uchun faqat YANGI dublikatlar bloklanadi.
        """
        email = self.cleaned_data["email"]
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Bu email bilan hisob allaqachon mavjud.")
        return email


class UserUpdateForm(forms.ModelForm):
    email = forms.EmailField()

    class Meta:
        model = User
        fields = ["username", "email"]

    def clean_email(self):
        """Email unikal [P6-T1] — o'z hisobidan boshqasiga tegishli bo'lmasin."""
        email = self.cleaned_data["email"]
        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Bu email boshqa hisobda ro'yxatdan o'tgan.")
        return email


class AsyncPasswordResetForm(PasswordResetForm):
    """Parol tiklash [P6-T1] — emailni Celery fonida yuboradi.

    Django'ning default send_mail'i SMTP'ni request siklida chaqiradi (sekin/
    ishonchsiz) — loyihada barcha email core.tasks.send_email_task orqali ketadi.
    """

    def send_mail(
        self,
        subject_template_name,
        email_template_name,
        context,
        from_email,
        to_email,
        html_email_template_name=None,
    ):
        subject = loader.render_to_string(subject_template_name, context)
        subject = "".join(subject.splitlines())  # sarlavha bir qatorda bo'lishi shart
        body = loader.render_to_string(email_template_name, context)
        send_email_task.delay(subject, body, [to_email])


class ProfileUpdateForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = ["avatar", "bio", "birth_date", "telegram_id", "notify_new_episode"]
        widgets = {
            # 🌟 O'ZGARTIRILGAN QISM
            "birth_date": SelectDateWidget(
                years=YEARS,
                empty_label=("Yil", "Oy", "Kun"),  # Tanlanmagan holatdagi yozuv
                attrs={
                    # Uchala quti uchun umumiy CSS klass (settings.html da buni to'g'rilaymiz)
                    "class": "custom-date-select outline-none focus:border-[#00cc4c] transition-colors cursor-pointer",
                },
            ),
            "bio": forms.Textarea(
                attrs={"placeholder": "O'zingiz haqingizda qisqacha...", "rows": 3}
            ),
            "telegram_id": forms.TextInput(attrs={"placeholder": "@username"}),
        }


# YANGA QO'SHILGAN FORMA
class TopUpRequestForm(forms.ModelForm):
    class Meta:
        model = TopUpRequest
        fields = ["amount_uzs", "receipt_image"]
        labels = {"amount_uzs": "To'lov summasi (UZS)", "receipt_image": "Chek rasmini yuklang"}
        widgets = {
            "amount_uzs": forms.NumberInput(
                attrs={
                    "placeholder": "Masalan: 10000",
                    "min": "1000",  # Eng kamida 1000 so'm
                    "class": "w-full bg-white/5 border border-white/10 rounded-2xl p-4 text-white outline-none focus:border-[#00cc4c] transition-colors",
                }
            ),
            "receipt_image": forms.FileInput(
                attrs={
                    "class": "w-full bg-white/5 border border-white/10 rounded-2xl p-3 text-gray-400 outline-none focus:border-[#00cc4c] file:mr-4 file:py-2.5 file:px-6 file:rounded-xl file:border-0 file:text-sm file:font-black file:bg-[#00cc4c] file:text-black hover:file:bg-[#00ff62] transition-colors cursor-pointer",
                    "accept": "image/*",
                }
            ),
        }


class CryptoTopUpRequestForm(forms.ModelForm):
    class Meta:
        model = CryptoTopUpRequest
        fields = ["amount_usdt", "receipt_image"]
        labels = {
            "amount_usdt": "To'lov summasi (USDT)",
            "receipt_image": "To'lov skrinshotini yuklang",
        }
        widgets = {
            "amount_usdt": forms.NumberInput(
                attrs={
                    "placeholder": "Masalan: 5.00",
                    "min": "1",
                    "step": "0.01",
                    "class": "w-full bg-white/5 border border-white/10 rounded-2xl p-4 text-white outline-none focus:border-[#0098EA] transition-colors",
                }
            ),
            "receipt_image": forms.FileInput(
                attrs={
                    "class": "w-full bg-white/5 border border-white/10 rounded-2xl p-3 text-gray-400 outline-none focus:border-[#0098EA] file:mr-4 file:py-2.5 file:px-6 file:rounded-xl file:border-0 file:text-sm file:font-black file:bg-[#0098EA] file:text-white hover:file:bg-[#007bc2] transition-colors cursor-pointer",
                    "accept": "image/*",
                }
            ),
        }
