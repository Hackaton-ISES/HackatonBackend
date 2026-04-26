from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

from tenders.models import UserProfile


@receiver(post_save, sender=User)
def ensure_profile_for_user(sender, instance: User, created: bool, **kwargs):
    if not created:
        return

    role = UserProfile.Role.ADMIN if instance.is_staff or instance.is_superuser else UserProfile.Role.COMPANY
    UserProfile.objects.get_or_create(
        user=instance,
        defaults={
            'role': role,
            'external_id': f'u-{instance.username.lower()}',
        },
    )
