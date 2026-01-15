from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, Profile

class ProfileInline(admin.StackedInline):
    model = Profile
    can_delete = False
    verbose_name_plural = "Profile Metadata"
    fk_name = "user"

@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """
    Modern User Management with integrated Profile metadata.
    """
    list_display = ["email", "first_name", "last_name", "is_staff", "is_active"]
    list_filter = ["is_staff", "is_superuser", "is_active"]
    inlines = [ProfileInline]
    
    # Redefining fieldsets for an email-based auth flow
    fieldsets = [
        (None, {"fields": ["email", "password"]}),
        ("Personal Info", {"fields": ["first_name", "last_name"]}),
        ("Permissions", {"fields": ["is_active", "is_staff", "is_superuser", "groups", "user_permissions"]}),
        ("Important dates", {"fields": ["last_login", "date_joined"]}),
    ]
    
    add_fieldsets = [
        (None, {
            "classes": ["wide"],
            "fields": ["email", "password"],
        }),
    ]
    
    search_fields = ["email", "first_name", "last_name"]
    ordering = ["email"]

@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    """
    Standalone Profile management using modern list syntax.
    """
    list_display = ["user"]
    search_fields = ["user__email"]