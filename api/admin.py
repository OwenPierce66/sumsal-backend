from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import UserChangeForm
from django.utils.translation import gettext_lazy as _
from django import forms
from .models import (
    User,
    Profile,
    Task,
    Like,
    LikeP,
    Favorito,
    pFavorito,
    NewPeticionCommentPost,
    LikeCommentPost,
    SharedTask,
    Portada,
    ImagenFija,
    Postt,
    NewCategory,
    CategoryP,
)


class ProfileInline(admin.StackedInline):
    model = Profile
    can_delete = False
    verbose_name_plural = _("profile")
    fields = [
        "id",
        "is_verified",
        "is_recommended",
        "subscriptionActive",
        "subscription_amount",
        "role",
    ]


class UserCreationForm(forms.ModelForm):
    password1 = forms.CharField(widget=forms.PasswordInput, label=_("Password"))
    password2 = forms.CharField(widget=forms.PasswordInput, label=_("Password confirmation"))

    class Meta:
        model = User
        fields = ("email", "is_staff", "is_superuser", "is_active")

    def clean_password2(self):
        password1 = self.cleaned_data.get("password1")
        password2 = self.cleaned_data.get("password2")
        if password1 and password2 and password1 != password2:
            raise forms.ValidationError(_("Passwords do not match"))
        return password2

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
        return user


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    form = UserChangeForm
    add_form = UserCreationForm
    inlines = (ProfileInline,)
    list_display = ("email", "first_name", "last_name", "is_staff", "is_active")
    list_filter = ("is_staff", "is_active", "is_superuser")
    search_fields = ("email", "first_name", "last_name")
    ordering = ("email",)

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (_("Personal info"), {"fields": ("first_name", "last_name")}),
        (
            _("Permissions"),
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                ),
            },
        ),
        (_("Important dates"), {"fields": ("last_login", "date_joined")}),
    )

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "email",
                    "password1",
                    "password2",
                    "is_staff",
                    "is_superuser",
                    "is_active",
                ),
            },
        ),
    )


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = [
        "user",
        "is_verified",
        "is_recommended",
        "subscriptionActive",
        "role",
        "created_at",
    ]
    search_fields = ["user__email", "user__first_name", "user__last_name"]
    list_filter = ["is_verified", "is_recommended", "subscriptionActive", "created_at"]
    readonly_fields = ["id", "user", "created_at", "updated_at"]

    fieldsets = (
        (_("Profile Basics"), {"fields": ("id", "user")}),
        (
            _("Verification"),
            {"fields": ("is_verified", "is_recommended")},
        ),
        (
            _("Subscription"),
            {"fields": ("subscriptionActive", "subscription_amount")},
        ),
        (_("Permissions"), {"fields": ("role",)}),
        (_("Important dates"), {"fields": ("created_at", "updated_at")}),
    )

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ["title", "user", "pch", "share_count", "created_at"]
    search_fields = ["title", "description", "user__email"]
    list_filter = ["pch", "created_at", "updated_at"]
    readonly_fields = ["id", "created_at", "updated_at"]

    fieldsets = (
        (_("Content"), {"fields": ("title", "description", "pch")}),
        (
            _("Details"),
            {"fields": ("username", "categories", "image", "video")},
        ),
        (_("Meta"), {"fields": ("user", "share_count", "created_at", "updated_at")}),
    )


@admin.register(Like)
class LikeAdmin(admin.ModelAdmin):
    list_display = ["user", "task", "created_at"]
    search_fields = ["user__email", "task__title"]
    list_filter = ["created_at"]
    readonly_fields = ["created_at"]


@admin.register(LikeP)
class LikePAdmin(admin.ModelAdmin):
    list_display = ["user", "profile", "created_at"]
    search_fields = ["user__email", "profile__email"]
    list_filter = ["created_at"]
    readonly_fields = ["created_at"]


@admin.register(Favorito)
class FavoritoAdmin(admin.ModelAdmin):
    list_display = ["user", "task", "created_at"]
    search_fields = ["user__email", "task__title"]
    list_filter = ["created_at"]
    readonly_fields = ["created_at"]


@admin.register(pFavorito)
class pFavoritoAdmin(admin.ModelAdmin):
    list_display = ["user", "perfil", "created_at"]
    search_fields = ["user__email", "perfil__email"]
    list_filter = ["created_at"]
    readonly_fields = ["created_at"]


@admin.register(SharedTask)
class SharedTaskAdmin(admin.ModelAdmin):
    list_display = ["task", "shared_by", "created_at"]
    search_fields = ["task__title", "shared_by__email"]
    list_filter = ["created_at"]
    readonly_fields = ["created_at"]


@admin.register(NewPeticionCommentPost)
class CommentAdmin(admin.ModelAdmin):
    list_display = ["created_by", "post", "is_parent", "created_at"]
    search_fields = ["created_by__email", "post__title", "text"]
    list_filter = ["created_at"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(LikeCommentPost)
class LikeCommentAdmin(admin.ModelAdmin):
    list_display = ["user", "comment", "created_at"]
    search_fields = ["user__email"]
    list_filter = ["created_at"]
    readonly_fields = ["created_at"]


@admin.register(Portada)
class PortadaAdmin(admin.ModelAdmin):
    list_display = ["title", "user", "created_at"]
    search_fields = ["title", "user__email"]
    list_filter = ["created_at"]
    readonly_fields = ["created_at"]


@admin.register(ImagenFija)
class ImagenFijaAdmin(admin.ModelAdmin):
    list_display = ["user", "created_at"]
    search_fields = ["user__email"]
    list_filter = ["created_at"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(Postt)
class PosttAdmin(admin.ModelAdmin):
    list_display = ["title", "user", "created_at"]
    search_fields = ["title", "content", "user__email"]
    list_filter = ["created_at"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(NewCategory)
class NewCategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "created_at"]
    search_fields = ["name"]
    list_filter = ["created_at"]
    readonly_fields = ["created_at"]


@admin.register(CategoryP)
class CategoryPAdmin(admin.ModelAdmin):
    list_display = ["name", "user", "created_at"]
    search_fields = ["name", "user__email"]
    list_filter = ["created_at"]
    readonly_fields = ["created_at"]
