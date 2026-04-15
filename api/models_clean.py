import uuid
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.conf import settings
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.core.files.storage import default_storage

try:
    from backend.storage_backends import ImagenText, VideoStorage
except ImportError:
    ImagenText = default_storage
    VideoStorage = default_storage



class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError(_('Users must have an email address'))
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)

        if extra_fields.get('is_staff') is not True:
            raise ValueError(_('Superuser must have is_staff=True.'))
        if extra_fields.get('is_superuser') is not True:
            raise ValueError(_('Superuser must have is_superuser=True.'))

        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    id = models.UUIDField(_('ID'), primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(_('email address'), unique=True)
    first_name = models.CharField(_('first name'), max_length=255, blank=True)
    last_name = models.CharField(_('last name'), max_length=255, blank=True)
    is_active = models.BooleanField(_('is active'), default=True)
    is_staff = models.BooleanField(_('is staff'), default=False)
    date_joined = models.DateTimeField(_('date joined'), default=timezone.now)
    updated_at = models.DateTimeField(_('updated at'), auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    class Meta:
        verbose_name = _('user')
        verbose_name_plural = _('users')
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
    is_verified = models.BooleanField(default=False)
    is_recommended = models.BooleanField(default=False)
    subscriptionActive = models.BooleanField(default=False)
    subscription_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    role = models.IntegerField(default=1)
    freeAccount = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('profile')
        verbose_name_plural = _('profiles')
        ordering = ['-user__date_joined']

    def __str__(self):
        return _('Profile for %(email)s') % {'email': self.user.email}


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
        return self.title or 'Task'


class Comment(models.Model):
    task = models.ForeignKey(Task, related_name='comments', on_delete=models.CASCADE)
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


class ImagenFija(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='imagenes_fijas')
    image = models.ImageField(storage=ImagenText(), null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"ImagenFija for {self.user.email}"


class Portada(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='portadas')
    title = models.CharField(max_length=1000, blank=True, default='')
    description = models.TextField(blank=True, default='')
    image = models.ImageField(storage=ImagenText(), null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Portada for {self.user.email}"


class Postt(models.Model):
    title = models.CharField(max_length=100)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    parent = models.ForeignKey('self', null=True, blank=True, related_name='replies', on_delete=models.CASCADE)

    def __str__(self):
        return self.title


class NewCategory(models.Model):
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name


class CategoryP(models.Model):
    name = models.CharField(max_length=100)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, related_name='categoriesp', on_delete=models.CASCADE)

    def __str__(self):
        return self.name


class LikeP(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, related_name='likes_given', on_delete=models.CASCADE)
    profile = models.ForeignKey(settings.AUTH_USER_MODEL, related_name='likes_received', on_delete=models.CASCADE)

    class Meta:
        unique_together = ('user', 'profile')


class TuModelo(models.Model):
    campo1 = models.CharField(max_length=100)
    campo2 = models.TextField()

    def __str__(self):
        return self.campo1


class Hashtag(models.Model):
    text = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.text


class Categoryy(models.Model):
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name


class NewPeticionCommentPost(models.Model):
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='task_comments')
    created_at = models.DateTimeField(auto_now_add=True)
    parent = models.ForeignKey('self', on_delete=models.CASCADE, blank=True, null=True, related_name='children')
    post = models.ForeignKey(Task, on_delete=models.CASCADE)
    aportacion = models.ForeignKey(Task, on_delete=models.SET_NULL, null=True, blank=True, related_name='aportacion_comments')
    text = models.TextField()

    @property
    def children(self):
        return NewPeticionCommentPost.objects.filter(parent=self).order_by('-created_at')

    @property
    def is_parent(self):
        return self.parent is None

    @property
    def like_set(self):
        return LikeCommentPost.objects.filter(comment=self)

    @property
    def subtasks(self):
        return SubTaskCommentPost.objects.filter(parent_task=self)

    @property
    def subFuentes(self):
        return SubFuentesCommentPost.objects.filter(parent_task=self)

    @property
    def subFactores(self):
        return SubFactoresCommentPost.objects.filter(parent_task=self)

    def __str__(self):
        return f"Comment by {self.created_by.email}: {self.text[:50]}"


class LikeCommentPost(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE)
    comment = models.ForeignKey(NewPeticionCommentPost, related_name='likes', on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Like by {self.user.email if self.user else 'Anonymous'} on comment {self.comment.id}"


class SubTaskCommentPost(models.Model):
    parent_task = models.ForeignKey(NewPeticionCommentPost, related_name='subtasks', on_delete=models.CASCADE)
    title = models.CharField(max_length=1000, blank=True, default='')
    description = models.TextField(blank=True, default='')
    link = models.TextField(blank=True, default='')
    image = models.ImageField(storage=ImagenText(), null=True, blank=True)
    video = models.FileField(storage=VideoStorage(), null=True, blank=True)

    def __str__(self):
        return self.title or 'SubTask Comment'


class SubFactoresCommentPost(models.Model):
    parent_task = models.ForeignKey(NewPeticionCommentPost, related_name='subFactores', on_delete=models.CASCADE)
    title = models.CharField(max_length=1000, blank=True, default='')
    description = models.TextField(blank=True, default='')
    link = models.TextField(blank=True, default='')
    image = models.ImageField(storage=ImagenText(), null=True, blank=True)
    video = models.FileField(storage=VideoStorage(), null=True, blank=True)

    def __str__(self):
        return self.title or 'SubFactor Comment'


class SubFuentesCommentPost(models.Model):
    parent_task = models.ForeignKey(NewPeticionCommentPost, related_name='subFuentes', on_delete=models.CASCADE)
    title = models.CharField(max_length=1000, blank=True, default='')
    description = models.TextField(blank=True, default='')
    link = models.TextField(blank=True, default='')
    image = models.ImageField(storage=ImagenText(), null=True, blank=True)
    video = models.FileField(storage=VideoStorage(), null=True, blank=True)

    def __str__(self):
        return self.title or 'SubFuente Comment'


class SubTask(models.Model):
    parent_task = models.ForeignKey(Task, related_name='subtasks', on_delete=models.CASCADE)
    title = models.CharField(max_length=1000, blank=True, default='')
    description = models.TextField(blank=True, default='')
    image = models.ImageField(storage=ImagenText(), null=True, blank=True)
    video = models.FileField(storage=VideoStorage(), null=True, blank=True)
    link = models.TextField(blank=True, default='')

    def __str__(self):
        return self.title or 'SubTask'


class SubFuentes(models.Model):
    parent_task = models.ForeignKey(Task, related_name='subfuentes', on_delete=models.CASCADE)
    title = models.CharField(max_length=1000, blank=True, default='')
    description = models.TextField(blank=True, default='')
    image = models.ImageField(storage=ImagenText(), null=True, blank=True)
    video = models.FileField(storage=VideoStorage(), null=True, blank=True)
    link = models.TextField(blank=True, default='')

    def __str__(self):
        return self.title or 'SubFuente'


class SubFactores(models.Model):
    parent_task = models.ForeignKey(Task, related_name='subfactores', on_delete=models.CASCADE)
    title = models.CharField(max_length=1000, blank=True, default='')
    description = models.TextField(blank=True, default='')
    image = models.ImageField(storage=ImagenText(), null=True, blank=True)
    video = models.FileField(storage=VideoStorage(), null=True, blank=True)
    link = models.TextField(blank=True, default='')

    def __str__(self):
        return self.title or 'SubFactor'


class NuevoTask(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE)
    title = models.CharField(max_length=1000, blank=True, default='')
    description = models.TextField(blank=True, default='')
    completed = models.BooleanField(default=False)
    username = models.TextField(blank=True, default='')
    categories = models.TextField(blank=True, default='')
    image = models.ImageField(storage=ImagenText(), null=True, blank=True)
    video = models.FileField(storage=VideoStorage(), null=True, blank=True)

    def __str__(self):
        return self.title or 'NuevoTask'


class Image(models.Model):
    task = models.ForeignKey(NuevoTask, related_name='images', on_delete=models.CASCADE)
    image = models.ImageField(storage=ImagenText(), blank=True, null=True)

    def __str__(self):
        return f'Image for {self.task.title}'


class Video(models.Model):
    task = models.ForeignKey(NuevoTask, related_name='videos', on_delete=models.CASCADE)
    video = models.FileField(storage=VideoStorage(), blank=True, null=True)

    def __str__(self):
        return f'Video for {self.task.title}'


class pFavorito(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, related_name='usuario_que_favoritos', on_delete=models.CASCADE)
    perfil = models.ForeignKey(settings.AUTH_USER_MODEL, related_name='perfiles_favoritos', on_delete=models.CASCADE)

    class Meta:
        unique_together = ('user', 'perfil')

    def __str__(self):
        return f"{self.user.email} favorited profile {self.perfil.email}"


class Imagen(models.Model):
    title = models.CharField(max_length=1000)
    description = models.TextField()
    image = models.ImageField(storage=ImagenText())

    def __str__(self):
        return self.title


class SharedTask(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name='shared_tasks')
    shared_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE, related_name='shared_tasks_by_user')
    description = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.task.title} shared by {self.shared_by.email if self.shared_by else 'unknown'}'
