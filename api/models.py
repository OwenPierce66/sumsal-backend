import uuid
from django.contrib.auth.models import (
    AbstractBaseUser,
    BaseUserManager,
    PermissionsMixin,
)
from django.db import models
from django.conf import settings
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("updated at"), auto_now=True)

    class Meta:
        abstract = True


class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError(_("Users must have an email address"))

        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save()
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.update(
            {
                "is_staff": True,
                "is_superuser": True,
                "is_active": True,
            }
        )

        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    id = models.UUIDField(_("id"), primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(_("email address"), unique=True)
    first_name = models.CharField(_("first name"), max_length=255, blank=True)
    last_name = models.CharField(_("last name"), max_length=255, blank=True)

    is_active = models.BooleanField(
        _("is active"),
        default=True,
        help_text=_("Unselect this instead of deleting accounts."),
    )
    is_staff = models.BooleanField(_("is staff"), default=False)
    date_joined = models.DateTimeField(_("date joined"), default=timezone.now)
    updated_at = models.DateTimeField(_("last updated"), auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        verbose_name = _("user")
        verbose_name_plural = _("users")
        ordering = ["-date_joined"]

    def __str__(self):
        return self.email


class Profile(TimeStampedModel):
    id = models.UUIDField(_("ID"), primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
        verbose_name=_("user"),
    )
    # Campos extendidos del código antiguo
    is_verified = models.BooleanField(_("is verified"), default=False)
    is_recommended = models.BooleanField(_("is recommended"), default=False)
    subscriptionActive = models.BooleanField(_("subscription active"), default=False)
    subscription_amount = models.DecimalField(
        _("subscription amount"), max_digits=10, decimal_places=2, default=0
    )
    role = models.IntegerField(
        _("role"),
        default=1,
        help_text=_("1=user, 2=editor, 3=admin")
    )

    class Meta:
        verbose_name = _("profile")
        verbose_name_plural = _("profiles")
        ordering = ["-user__date_joined"]

    def __str__(self):
        return _("Profile for %(email)s") % {"email": self.user.email}


# ============================================================================
# MODELOS DE CONTENIDO (Tareas, Comentarios, Likes, etc.)
# ============================================================================

class NewCategory(models.Model):
    """Categorías globales de tareas"""
    name = models.CharField(_("name"), max_length=100, unique=True)
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)

    class Meta:
        verbose_name = _("new category")
        verbose_name_plural = _("new categories")
        ordering = ["name"]

    def __str__(self):
        return self.name


class CategoryP(models.Model):
    """Categorías personales del usuario"""
    name = models.CharField(_("name"), max_length=100)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="categoriesp",
        verbose_name=_("user"),
    )
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)

    class Meta:
        verbose_name = _("category P")
        verbose_name_plural = _("categories P")
        unique_together = ("user", "name")

    def __str__(self):
        return f"{self.name} ({self.user.email})"


class Task(TimeStampedModel):
    """Tareas/Peticiones principales"""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="tasks",
        verbose_name=_("user"),
    )
    title = models.CharField(_("title"), max_length=1000, blank=True, default="")
    description = models.TextField(_("description"), blank=True, default="")
    pch = models.TextField(_("pch"), blank=True, default="", help_text=_("Type: consejos, peticiones, historias"))
    username = models.TextField(_("username"), blank=True, default="")
    categories = models.TextField(_("categories"), blank=True, default="")
    image = models.ImageField(upload_to="tasks/", null=True, blank=True)
    video = models.FileField(upload_to="tasks/videos/", null=True, blank=True)
    share_count = models.PositiveIntegerField(_("share count"), default=0)

    class Meta:
        verbose_name = _("task")
        verbose_name_plural = _("tasks")
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["-created_at"])]

    def __str__(self):
        return self.title[:50]


class Like(TimeStampedModel):
    """Likes en tareas"""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="task_likes",
        verbose_name=_("user"),
    )
    task = models.ForeignKey(
        Task,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="likes",
        verbose_name=_("task"),
    )

    class Meta:
        verbose_name = _("like")
        verbose_name_plural = _("likes")
        unique_together = ("user", "task")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user.email if self.user else 'Unknown'} likes {self.task}"


class LikeP(models.Model):
    """Likes en perfiles de usuario"""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="likes_given",
        on_delete=models.CASCADE,
        verbose_name=_("user"),
    )
    profile = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="likes_received",
        on_delete=models.CASCADE,
        verbose_name=_("profile"),
    )
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)

    class Meta:
        verbose_name = _("profile like")
        verbose_name_plural = _("profile likes")
        unique_together = ("user", "profile")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user.email} likes {self.profile.email}"


class Favorito(models.Model):
    """Favoritos de tareas"""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="favoritos",
        on_delete=models.CASCADE,
        verbose_name=_("user"),
    )
    task = models.ForeignKey(
        Task,
        related_name="favoritos",
        on_delete=models.CASCADE,
        verbose_name=_("task"),
    )
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)

    class Meta:
        verbose_name = _("favorite")
        verbose_name_plural = _("favorites")
        unique_together = ("user", "task")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user.email} favorites {self.task.title[:30]}"


class pFavorito(models.Model):
    """Favoritos de perfiles de usuario"""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="usuario_que_favoritos",
        on_delete=models.CASCADE,
        verbose_name=_("user"),
        help_text=_("El usuario que marca como favorito"),
    )
    perfil = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="perfiles_favoritos",
        on_delete=models.CASCADE,
        verbose_name=_("profile"),
        help_text=_("El perfil marcado como favorito"),
    )
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)

    class Meta:
        verbose_name = _("profile favorite")
        verbose_name_plural = _("profile favorites")
        unique_together = ("user", "perfil")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user.email} favorites {self.perfil.email}"


class SharedTask(TimeStampedModel):
    """Tareas compartidas"""
    task = models.ForeignKey(
        Task,
        on_delete=models.CASCADE,
        related_name="shared_tasks",
        verbose_name=_("task"),
    )
    shared_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="shared_tasks_by_user",
        verbose_name=_("shared by"),
    )
    description = models.TextField(_("description"), blank=True, default="")

    class Meta:
        verbose_name = _("shared task")
        verbose_name_plural = _("shared tasks")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.task.title[:30]} shared by {self.shared_by.email if self.shared_by else 'Unknown'}"


class NewPeticionCommentPost(TimeStampedModel):
    """Comentarios en tareas (jerárquico)"""
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="task_comments",
        verbose_name=_("created by"),
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name="children",
        verbose_name=_("parent comment"),
    )
    post = models.ForeignKey(
        Task,
        on_delete=models.CASCADE,
        related_name="comments",
        verbose_name=_("task"),
    )
    aportacion = models.ForeignKey(
        Task,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="aportacion_comments",
        verbose_name=_("contribution"),
    )
    text = models.TextField(_("text"))

    class Meta:
        verbose_name = _("comment")
        verbose_name_plural = _("comments")
        ordering = ["-created_at"]

    def __str__(self):
        return f"Comment by {self.created_by.email} on {self.post.title[:30]}"

    @property
    def is_parent(self):
        return self.parent is None


class LikeCommentPost(TimeStampedModel):
    """Likes en comentarios"""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="comment_likes",
        verbose_name=_("user"),
    )
    comment = models.ForeignKey(
        NewPeticionCommentPost,
        related_name="likes",
        on_delete=models.CASCADE,
        verbose_name=_("comment"),
    )

    class Meta:
        verbose_name = _("comment like")
        verbose_name_plural = _("comment likes")
        unique_together = ("user", "comment")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user.email if self.user else 'Unknown'} likes comment"


# ============================================================================
# MODELOS DE IMAGEN/PERFIL
# ============================================================================

class Portada(models.Model):
    """Imagen de portada de usuario"""
    title = models.CharField(_("title"), max_length=255, null=True, blank=True)
    image = models.ImageField(upload_to="portadas/", null=True, blank=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="portadas",
        verbose_name=_("user"),
    )
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)

    class Meta:
        verbose_name = _("portada")
        verbose_name_plural = _("portadas")
        ordering = ["-created_at"]

    def __str__(self):
        return f"Portada: {self.title or self.user.email}"


class ImagenFija(TimeStampedModel):
    """Imagen de perfil fija"""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="imagenes_fijas",
        verbose_name=_("user"),
    )
    image = models.ImageField(upload_to="imagenfija/", null=True, blank=True)

    class Meta:
        verbose_name = _("fixed image")
        verbose_name_plural = _("fixed images")
        ordering = ["-created_at"]

    def __str__(self):
        return f"Image: {self.user.email}"


class Postt(TimeStampedModel):
    """Posts/Foros simples"""
    title = models.CharField(_("title"), max_length=100)
    content = models.TextField(_("content"))
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="posts",
        verbose_name=_("user"),
    )
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        related_name="replies",
        on_delete=models.CASCADE,
        verbose_name=_("parent"),
    )

    class Meta:
        verbose_name = _("postt")
        verbose_name_plural = _("postts")
        ordering = ["-created_at"]

    def __str__(self):
        return self.title
