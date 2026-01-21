from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from django.contrib import messages
from django import forms
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
    
    list_display = ["email", "is_staff", "is_active", "date_joined", 'updated_at', 'id']
    search_fields = ["email", 'first_name', 'last_name', "id"]
    list_filter = ['first_name', 'last_name', "is_staff", "is_active", "date_joined", 'updated_at']
    readonly_fields = ["id", 'email', 'password', 'first_name', 'last_name', 'last_login', "date_joined", "updated_at"]

    inlines = [ProfileInline]
    
    fieldsets = (
        (_("Account Basics"), {"fields": ("email", 'first_name', 'last_name', "password", 'id')}),
        (_("Permissions"), {"fields": ("is_staff", "is_active", "is_superuser", "groups", "user_permissions")}),
        (_("Important dates"), {"fields": ("last_login", "date_joined", 'updated_at')}),
    )
    
    add_fieldsets = (
        (_("Create New User"), {
            "classes": ("wide",),
            "fields": ("email", "password", "is_staff"),
        }),
    )

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

@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin): 
    list_display = ["user", 'get_first_name', 'get_last_name', 'created_at', 'updated_at', "id",]
    search_fields = ["user__email", 'user__first_name', 'user__last_name', "id"]
    list_filter = ["created_at", 'updated_at']
    readonly_fields = ['id', 'user', 'created_at', 'updated_at']

    fieldsets = (
        (_("Profile Basics"), {"fields": ("user", 'id')}),
        (_("Important dates"), {"fields": ("created_at", 'updated_at')}),
    )

    @admin.display(description=_("first name"))
    def get_first_name(self, obj):
        return obj.user.first_name

    @admin.display(description=_("last name"))
    def get_last_name(self, obj):
        return obj.user.last_name

    def has_delete_permission(self, request, obj=None):
        return False