# models.py
from django.db import models
from django.conf import settings
from Sumsal_Backend.storage_backends import ImagenText, VideoStorage  # Asegúrate de que los imports de storage sean correctos


class Message(models.Model):
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name='sent_messages',
        on_delete=models.CASCADE
    )
    receiver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name='received_messages',
        on_delete=models.CASCADE
    )
    content = models.TextField(blank=True, null=True)
    translated_content = models.TextField(blank=True, null=True)
    image = models.ImageField(storage=ImagenText(), null=True, blank=True)
    video = models.FileField(storage=VideoStorage(), null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)

    # 👇 NUEVO: referencia al mensaje al que responde (opcional)
    replied_to = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        related_name='replies',
        on_delete=models.SET_NULL,
    )

    def __str__(self):
        return f'Message from {self.sender} to {self.receiver}'




class MessageLike(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    message = models.ForeignKey(
        Message,
        related_name='likes',
        on_delete=models.CASCADE
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'message')

    def __str__(self):
        return f'{self.user} liked {self.message_id}'


class MessageAttachment(models.Model):
    message = models.ForeignKey(
        Message,
        related_name='attachments',
        on_delete=models.CASCADE
    )
    file = models.FileField(
        upload_to='messages/attachments/',
        storage=VideoStorage()
    )
    file_type = models.CharField(max_length=100, blank=True)
    is_image = models.BooleanField(default=False)
    is_video = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        if self.file and not self.file_type:
            ct = getattr(self.file, 'content_type', '') or ''
            self.file_type = ct
            if ct.startswith('image/'):
                self.is_image = True
            elif ct.startswith('video/'):
                self.is_video = True
        super().save(*args, **kwargs)

    def __str__(self):
        return f'Attachment {self.id} of message {self.message_id}'


class Group(models.Model):
    name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name='created_groups',
        on_delete=models.CASCADE
    )
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through='GroupMembership'
    )

    def __str__(self):
        return self.name


class GroupMembership(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    group = models.ForeignKey(Group, on_delete=models.CASCADE)
    is_admin = models.BooleanField(default=False)
    joined_at = models.DateTimeField(auto_now_add=True)
    last_read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'group'],
                name='unique_group_membership',
            ),
        ]

    def __str__(self):
        return f'{self.user} in {self.group} (admin={self.is_admin})'


class GroupMessage(models.Model):
    group = models.ForeignKey(
        Group,
        related_name='messages',
        on_delete=models.CASCADE
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name='sent_group_messages',
        on_delete=models.CASCADE
    )
    content = models.TextField(blank=True, null=True)
    image = models.ImageField(storage=ImagenText(), null=True, blank=True)
    video = models.FileField(storage=VideoStorage(), null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    # 👇 NUEVO: referencia al mensaje de grupo al que responde
    replied_to = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        related_name='replies',
        on_delete=models.SET_NULL,
    )

    def __str__(self):
        return f'Message from {self.sender} in group {self.group}'


class GroupMessageAttachment(models.Model):
    message = models.ForeignKey(
        GroupMessage,
        related_name='attachments',
        on_delete=models.CASCADE
    )
    file = models.FileField(
        upload_to='group_messages/attachments/',
        storage=VideoStorage()
    )
    file_type = models.CharField(max_length=100, blank=True)
    is_image = models.BooleanField(default=False)
    is_video = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        if self.file and not self.file_type:
            ct = getattr(self.file, 'content_type', '') or ''
            self.file_type = ct
            if ct.startswith('image/'):
                self.is_image = True
            elif ct.startswith('video/'):
                self.is_video = True
        super().save(*args, **kwargs)

    def __str__(self):
        return f'Attachment {self.id} of group message {self.message_id}'