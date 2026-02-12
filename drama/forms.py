from django import forms
from .models import Review

class ReviewForm(forms.ModelForm):
    class Meta:
        model = Review
        fields = ("text",)
        widgets = {
            "text": forms.Textarea(attrs={
                "class": "w-full bg-gray-900 border border-gray-800 rounded-xl p-4 text-sm text-white focus:outline-none focus:border-[#00cc4c] transition",
                "rows": "3",
                "placeholder": "Fikringizni yozing..."
            })
        }