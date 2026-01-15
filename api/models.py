import uuid
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.conf import settings
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("Users must have an email address")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        return self.create_user(email, password, **extra_fields)

class User(AbstractBaseUser, PermissionsMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    email = models.EmailField(_('email address'), unique=True, db_index=True)
    first_name = models.CharField(_("first name"), max_length=255, blank=True)
    last_name = models.CharField(_("last name"), max_length=255, blank=True)
    
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []  # Email is already required by USERNAME_FIELD

    class Meta:
        verbose_name = _("user")
        verbose_name_plural = _("users")
        indexes = [models.Index(fields=['email'])]

    def __str__(self):
        return self.email

class Profile(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # user = models.OneToOneField('api.User', on_delete=models.CASCADE, related_name='profile')
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, # <--- Use this instead of 'api.User'
        on_delete=models.CASCADE, 
        related_name='profile'
    )
    # avatar = models.ImageField(upload_to='avatars/', null=True, blank=True)
    # bio = models.TextField(blank=True)

    def __str__(self):
        return f"Profile for {self.user.email}"
