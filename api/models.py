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

# Etiqueta reservada de aprobación (podcasts/peticiones). Solo staff puede ponerla.
APPROVED_TAG = "aprobada"
# Categoría que convierte una publicación en propuesta de podcast.
PODCAST_CATEGORY = "Grabar Podcast"

# Etiquetas de estado: viven en `categories` pero no son categorías de filtro.
STATUS_TAGS = {"aprobada", "aprobadas", "procesando"}

# Espejo del árbol de subtemas del cliente: lo que aparezca aquí NO es categoría principal.
DEFAULT_SUBTHEMES = {
    "programacion": ["React", "Python", "Node.js", "Django", "React Native", "JavaScript", "Frontend", "Backend"],
    "tecnologia": ["Inteligencia Artificial", "Ciberseguridad", "Hardware", "Software", "Innovación"],
    "educacion": ["Matemáticas", "Idiomas", "Ciencias", "Historia", "Pedagogía"],
    "salud": ["Nutrición", "Ejercicio", "Bienestar Mental", "Medicina", "Psicología"],
    "finanzas": ["Inversiones", "Ahorro", "Criptomonedas", "Emprendimiento", "Economía"],
    "arte": ["Pintura", "Música", "Fotografía", "Cine", "Diseño"],
    "deportes": ["Fútbol", "Baloncesto", "Tenis", "Natación", "Fitness"],
}
SUBTHEME_NAMES = {
    name.casefold() for names in DEFAULT_SUBTHEMES.values() for name in names
}

# ============================================================================
# CLASES BASE Y GESTIÓN DE USUARIOS
# ============================================================================

class TimeStampedModel(models.Model):
    """Clase abstracta para añadir timestamps automáticamente"""
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
        extra_fields.update({"is_staff": True, "is_superuser": True, "is_active": True})
        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """Modelo de Usuario Sumsal con UUID e Email"""
    id = models.UUIDField(_("id"), primary_key=True, default=uuid.uuid4, editable=False)
    username = models.CharField(_("username"), max_length=150, unique=True, null=True, blank=True)
    email = models.EmailField(_("email address"), unique=True)
    first_name = models.CharField(_("first name"), max_length=255, blank=True)
    last_name = models.CharField(_("last name"), max_length=255, blank=True)
    is_active = models.BooleanField(_("is active"), default=True)
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
    """Perfil extendido para la lógica de la app"""
    id = models.UUIDField(_("ID"), primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
        verbose_name=_("user"),
    )
    is_verified = models.BooleanField(_("is verified"), default=False)
    is_recommended = models.BooleanField(_("is recommended"), default=False)
    subscriptionActive = models.BooleanField(_("subscription active"), default=False)
    subscription_amount = models.DecimalField(
        _("subscription amount"), max_digits=10, decimal_places=2, default=0
    )
    personal_filter_public = models.BooleanField(
        _("show personal filter everywhere"), default=False
    )
    role = models.IntegerField(_("role"), default=1, help_text=_("1=user, 2=editor, 3=admin"))

    class Meta:
        verbose_name = _("profile")
        verbose_name_plural = _("profiles")
        ordering = ["-user__date_joined"]

    def __str__(self):
        return f"Profile for {self.user.email}"


class Notification(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="triggered_notifications",
    )
    notification_type = models.CharField(max_length=64)
    target_type = models.CharField(max_length=32)
    target_id = models.CharField(max_length=255)
    secondary_target_type = models.CharField(max_length=32, blank=True, default="")
    secondary_target_id = models.CharField(max_length=255, blank=True, default="")
    data = models.JSONField(default=dict, blank=True)
    dedupe_key = models.CharField(max_length=255, blank=True, default="")
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["recipient", "is_read", "-created_at"],
                name="notification_rec_read_idx",
            ),
            models.Index(
                fields=["target_type", "target_id"],
                name="notification_target_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["recipient", "dedupe_key"],
                condition=~models.Q(dedupe_key=""),
                name="notification_rec_dedupe_uniq",
            )
        ]

    def __str__(self):
        return f"{self.notification_type} for {self.recipient_id}"


class UserSavedFilter(TimeStampedModel):
    """Filtro propio guardado por el usuario en su perfil (CRUD).
    `filters` guarda en un solo campo JSON el mismo payload que produce
    el modal de filtros (category, status, date_filter, sort_by, etc.),
    para poder reaplicarlo sin tener que renderizar todas las tareas."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="saved_filters",
    )
    name = models.CharField(_("name"), max_length=120)
    filters = models.JSONField(default=dict, blank=True)

    class Meta:
        unique_together = ("user", "name")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.user_id})"


# ============================================================================
# CONTENIDO Y CATEGORÍAS
# ============================================================================

class NewCategory(models.Model):
    name = models.CharField(_("name"), max_length=100)
    # Vacío = categoría global (visible en todos los tipos de aportación).
    pch = models.CharField(
        _("pch"), max_length=20, blank=True, default="",
        help_text=_("Tipo de aportación dueño de esta categoría (consejos/peticiones/historias)"),
    )
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.CASCADE, related_name="children"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "New Categories"
        unique_together = ("name", "pch")

    def __str__(self):
        return self.name


class CategoryP(models.Model):
    """Filtro personal del usuario: árbol de categorías propias (padre/hijo sin
    límite de profundidad), guardado aparte para consultarlo sin recorrer tareas."""
    name = models.CharField(_("name"), max_length=100)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="categoriesp")
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.CASCADE, related_name="children"
    )
    position = models.PositiveIntegerField(_("position"), default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "name", "parent")
        ordering = ["position", "created_at"]

    def __str__(self):
        return f"{self.name} ({self.user.email})"


class Task(TimeStampedModel):
    """Modelo principal de Peticiones/Recetas/Tareas"""
    # ✅ FIX: Estandarizar a UUID para consistencia en toda la app.
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="tasks"
    )
    title = models.CharField(_("title"), max_length=1000, blank=True, default="")
    description = models.TextField(_("description"), blank=True, default="")
    pch = models.TextField(_("pch type"), blank=True, default="")
    username = models.TextField(blank=True, default="")
    categories = models.TextField(blank=True, default="")
    image = models.ImageField(upload_to="tasks/", null=True, blank=True)
    video = models.FileField(upload_to="tasks/videos/", null=True, blank=True)
    story_is_shared = models.BooleanField(default=False)
    story_source_task = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="story_copies",
    )
    share_count = models.PositiveIntegerField(default=0)
    interaction_score = models.IntegerField(default=0, help_text=_("Score for feed ranking"))

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title or "Untitled Task"


# ============================================================================
# SOCIAL: LIKES, FAVORITOS Y COMPARTIDOS
# ============================================================================

class Like(TimeStampedModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="task_likes")
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="likes")

    class Meta:
        unique_together = ("user", "task")


class StoryView(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    story = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="story_views")
    viewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="story_views",
    )
    viewed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["story", "viewer"],
                name="story_view_story_viewer_uniq",
            )
        ]
        indexes = [
            models.Index(
                fields=["story", "-viewed_at"],
                name="story_view_story_date_idx",
            )
        ]


class LikeP(models.Model):
    """Likes entre perfiles"""
    # ✅ FIX DEFINITIVO: Cambiamos la relación de Profile a User.
    # El código existente (vistas, serializadores) ya pasaba un objeto User,
    # lo que causaba un error fatal en la base de datos y tumbaba el servidor (Error 502).
    # Al alinear el modelo con el uso real, eliminamos la causa raíz del problema.
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="likes_given")
    profile = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="likes_received")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "profile")

class Favorito(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="user_favorites")
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="favorited_by")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "task")


class pFavorito(models.Model):
    """Favoritos de perfiles/usarios."""
    # Mantener esta relación en User para coincidir con el esquema real de Postgres.
    # El campo `perfil_id` en la base viva apunta a `api_user`, no a `api_profile`.
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile_favorites_given")
    perfil = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile_favorites_received")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "perfil")


class SharedTask(TimeStampedModel):
    # ✅ FIX: Estandarizar a UUID para consistencia.
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="shared_instances")
    shared_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="shares")
    description = models.TextField(blank=True, default="")


class TaskTag(TimeStampedModel):
    """Personas etiquetadas en una tarea/publicación (tag común de redes sociales)."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="tagged_users")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="tagged_in_tasks",
    )
    tagged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="tags_made",
    )

    class Meta:
        unique_together = ("task", "user")

    def __str__(self):
        return f"{self.user_id} tagged in {self.task_id}"


class PodcastInvitation(TimeStampedModel):
    """Respuesta individual de una persona invitada a un podcast aprobado."""
    STATUS_PENDING = "pending"
    STATUS_ACCEPTED = "accepted"
    STATUS_DECLINED = "declined"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pendiente"),
        (STATUS_ACCEPTED, "Aceptada"),
        (STATUS_DECLINED, "Rechazada"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="podcast_invitations")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="podcast_invitations",
    )
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING)
    responded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ("task", "user")


# ============================================================================
# COMENTARIOS Y JERARQUÍA
# ============================================================================

class NewPeticionCommentPost(TimeStampedModel):
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="comments")
    parent = models.ForeignKey("self", on_delete=models.CASCADE, null=True, blank=True, related_name="replies")
    
    # ✅ FIX MIGRATIONS: Se especifican related_name únicos para evitar conflictos
    # al tener dos ForeignKey apuntando al mismo modelo (Task).
    post = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="post_comments")
    aportacion = models.ForeignKey(Task, on_delete=models.SET_NULL, null=True, blank=True, related_name="aportacion_comments")
    
    text = models.TextField(_("comment text"))

    class Meta:
        ordering = ["-created_at"]


class LikeCommentPost(TimeStampedModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="comment_likes")
    comment = models.ForeignKey(NewPeticionCommentPost, on_delete=models.CASCADE, related_name="likes")

    class Meta:
        unique_together = ("user", "comment")


# ============================================================================
# COMENTARIOS Y LIKES PARA TAREAS COMPARTIDAS
# ============================================================================

class SharedTaskComment(TimeStampedModel):
    """Comentarios anidados para tareas compartidas"""
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="shared_task_comments")
    parent = models.ForeignKey("self", on_delete=models.CASCADE, null=True, blank=True, related_name="replies")
    shared_task = models.ForeignKey(SharedTask, on_delete=models.CASCADE, related_name="comments")
    text = models.TextField(_("comment text"))

    class Meta:
        ordering = ["-created_at"]


class LikeSharedTaskComment(TimeStampedModel):
    """Likes para comentarios de tareas compartidas"""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="shared_task_comment_likes")
    comment = models.ForeignKey(SharedTaskComment, on_delete=models.CASCADE, related_name="likes")

    class Meta:
        unique_together = ("user", "comment")


class LikeSharedTask(TimeStampedModel):
    """Likes para tareas compartidas (independiente del like de la tarea original)"""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="shared_task_likes")
    shared_task = models.ForeignKey(SharedTask, on_delete=models.CASCADE, related_name="likes")

    class Meta:
        unique_together = ("user", "shared_task")


# ============================================================================
# IMÁGENES Y OTROS
# ============================================================================

class Portada(models.Model):
    title = models.CharField(max_length=255, null=True, blank=True)
    image = models.ImageField(upload_to="portadas/", null=True, blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="portadas")
    created_at = models.DateTimeField(auto_now_add=True)


class ImagenFija(TimeStampedModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="fixed_images")
    image = models.ImageField(upload_to="fixed/", null=True, blank=True)


class Postt(TimeStampedModel):
    """Hilo de foro simple"""
    title = models.CharField(max_length=100, blank=True)
    content = models.TextField()
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="forum_posts")
    parent = models.ForeignKey("self", on_delete=models.CASCADE, null=True, blank=True, related_name="forum_replies")


class LikePostt(TimeStampedModel):
    """Likes para posts del foro"""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="post_likes")
    post = models.ForeignKey(Postt, on_delete=models.CASCADE, related_name="likes")

    class Meta:
        unique_together = ("user", "post")


# ============================================================================
# APORTACIONES INTERNAS (SUBTASKS, FUENTES, FACTORES)
# ============================================================================

class SubTask(models.Model):
    parent_task = models.ForeignKey(Task, related_name='subtasks', on_delete=models.CASCADE)
    title = models.CharField(max_length=1000, blank=True, default='')
    description = models.TextField(blank=True, default='')
    image = models.ImageField(upload_to="subtasks/images/", null=True, blank=True)
    video = models.FileField(upload_to="subtasks/videos/", null=True, blank=True)
    link = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

class SubFuentes(models.Model):
    parent_task = models.ForeignKey(Task, related_name='subfuentes', on_delete=models.CASCADE)
    title = models.CharField(max_length=1000, blank=True, default='')
    description = models.TextField(blank=True, default='')
    image = models.ImageField(upload_to="subfuentes/images/", null=True, blank=True)
    video = models.FileField(upload_to="subfuentes/videos/", null=True, blank=True)
    link = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

class SubFactores(models.Model):
    parent_task = models.ForeignKey(Task, related_name='subfactores', on_delete=models.CASCADE)
    title = models.CharField(max_length=1000, blank=True, default='')
    description = models.TextField(blank=True, default='')
    image = models.ImageField(upload_to="subfactores/images/", null=True, blank=True)
    video = models.FileField(upload_to="subfactores/videos/", null=True, blank=True)
    link = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

# Tambien faltan los comentarios de los Subtasks, añadimos las referencias base
class SubTaskCommentPost(models.Model):
    parent_task = models.ForeignKey(NewPeticionCommentPost, related_name='subtasks', on_delete=models.CASCADE)
    title = models.CharField(max_length=1000, blank=True, default='')
    description = models.TextField(blank=True, default='')
    link = models.TextField(blank=True, default='')
    image = models.ImageField(upload_to="comments/subtasks/images/", null=True, blank=True)
    video = models.FileField(upload_to="comments/subtasks/videos/", null=True, blank=True)

class SubFactoresCommentPost(models.Model):
    parent_task = models.ForeignKey(NewPeticionCommentPost, related_name='subfactores', on_delete=models.CASCADE)
    title = models.CharField(max_length=1000, blank=True, default='')
    description = models.TextField(blank=True, default='')
    link = models.TextField(blank=True, default='')
    image = models.ImageField(upload_to="comments/subfactores/images/", null=True, blank=True)
    video = models.FileField(upload_to="comments/subfactores/videos/", null=True, blank=True)

class SubFuentesCommentPost(models.Model):
    parent_task = models.ForeignKey(NewPeticionCommentPost, related_name='subfuentes', on_delete=models.CASCADE)
    title = models.CharField(max_length=1000, blank=True, default='')
    description = models.TextField(blank=True, default='')
    link = models.TextField(blank=True, default='')
    image = models.ImageField(upload_to="comments/subfuentes/images/", null=True, blank=True)
    video = models.FileField(upload_to="comments/subfuentes/videos/", null=True, blank=True)