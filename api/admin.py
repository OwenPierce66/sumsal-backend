from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from django.contrib import messages
from django import forms
from django.contrib.auth.forms import ReadOnlyPasswordHashField
from .models import User, Profile

class ProfileInline(admin.StackedInline):
    model = Profile
    can_delete = False
    verbose_name_plural = _("Profile Metadata")
    fk_name = "user"
    fields = ['id'] 
    readonly_fields = ['id']
    extra = 0

class UserCreationForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput, label=_("Password"))
    
    class Meta:
        model = User
        fields = ("email", "password", "is_staff")

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password"])
        if commit:
            user.save()
        return user

@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    add_form = UserCreationForm
    
    list_display = ["email", "is_staff", "is_active", "date_joined"]
    list_filter = ["is_staff", "is_active"]
    inlines = [ProfileInline]
    
    fieldsets = (
        (_("Account Basics"), {"fields": ("id", "email", "password")}),
        (_("Permissions"), {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        (_("Important dates"), {"fields": ("last_login", "date_joined")}),
    )
    
    add_fieldsets = (
        (_("Create New User"), {
            "classes": ("wide",),
            "fields": ("email", "password", "is_staff"),
        }),
    )
    
    readonly_fields = ["id", "date_joined", "last_login"]

    def get_form(self, request, obj=None, **kwargs):
        if obj is None:
            return self.add_form
        return super().get_form(request, obj, **kwargs)

    def get_fieldsets(self, request, obj=None):
        if not obj:
            return self.add_fieldsets
        return super().get_fieldsets(request, obj)

    def get_inlines(self, request, obj=None):
        return [ProfileInline] if obj else []

    def response_add(self, request, obj, post_url_continue=None):
        messages.success(request, _("🚀 Boom! User %(email)s is now live.") % {'email': obj.email})
        return super().response_add(request, obj, post_url_continue)