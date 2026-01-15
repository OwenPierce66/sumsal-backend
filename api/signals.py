from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model
from .models import Profile

# This is the safe way to get your Custom User model in signals
User = get_user_model()

@receiver(post_save, sender=User)
def manage_user_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.create(user=instance)
    else:
        # Using getattr to avoid errors if a profile somehow doesn't exist
        if hasattr(instance, 'profile'):
            instance.profile.save()