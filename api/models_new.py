import uuid
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.conf import settings
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

# Importar storages del código antiguo
try:
    from Sumsal_Backend.storage_backends import ImagenText, VideoStorage
except ImportError:
    # Fallback si no existe
    from django.core.files.storage import default_storage
    ImagenText = default_storage
    VideoStorage = default_storage


class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError(_("Users must have an email address"))
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError(_("Superuser must have is_staff=True."))
        if extra_fields.get("is_superuser") is not True:
            raise ValueError(_("Superuser must have is_superuser=True."))

        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    id = models.UUIDField(_('ID'), primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(_('email address'), unique=True)
    first_name = models.CharField(_("first name"), max_length=255, blank=True)
    last_name = models.CharField(_("last name"), max_length=255, blank=True)

    is_active = models.BooleanField(_('is active'), default=True)
    is_staff = models.BooleanField(_('is staff'), default=False)
    date_joined = models.DateTimeField(_('date joined'), default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        verbose_name = _("user")
        verbose_name_plural = _("users")
        ordering = ['-date_joined']

    def __str__(self):
        return _('User %(email)s') % {'email': self.email}


class Profile(models.Model):
    id = models.UUIDField(_('ID'), primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='profile',
        verbose_name=_('user'),
    )

    # Campos adicionales del código antiguo
    is_verified = models.BooleanField(default=False)
    is_recommended = models.BooleanField(default=False)
    subscriptionActive = models.BooleanField(default=False)
    subscription_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    role = models.IntegerField(default=1)  # 1=user, 2=editor, 3=admin
    freeAccount = models.BooleanField(default=True)

    class Meta:
        verbose_name = _("profile")
        verbose_name_plural = _("profiles")
        ordering = ['-user__date_joined']

    def __str__(self):
        return _("Profile for %(email)s") % {'email': self.user.email}


# Modelos del código antiguo adaptados a Sumsal
class Task(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE)
    title = models.CharField(max_length=1000, blank=True, default='')
    description = models.TextField(blank=True, default='')
    pch = models.TextField(blank=True, default='')
    username = models.TextField(blank=True, default='')
    categories = models.TextField(blank=True, default='')
    image = models.ImageField(storage=ImagenText(), null=True, blank=True)
    video = models.FileField(storage=VideoStorage(), null=True, blank=True)
    share_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True, db_index=True)

    def __str__(self):
        return self.title or "Task"


class Comment(models.Model):
    task = models.ForeignKey(Task, related_name="comments", on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE)
    userId = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    title = models.CharField(max_length=1000)
    description = models.TextField()
    username = models.TextField()
    image = models.ImageField(storage=ImagenText())

    def __str__(self):
        return self.title


class Like(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    task = models.ForeignKey(Task, null=True, blank=True, on_delete=models.CASCADE)

    def __str__(self):
        return f"Like by {self.user.email if self.user else 'Anonymous'} on {self.task.title if self.task else 'Unknown task'}"


class Favorito(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, related_name='favoritos', on_delete=models.CASCADE)
    task = models.ForeignKey(Task, related_name='favoritos', on_delete=models.CASCADE)

    class Meta:
        unique_together = ('user', 'task')

    def __str__(self):
        return f"{self.user.email} favorited {self.task.title}"