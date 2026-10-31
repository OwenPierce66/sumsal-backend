"""Grupos de la red social: reglas de membresía, roles y revisión de publicaciones.

- Cualquiera crea un grupo y queda como su creador (rol `owner`, también admin).
- Público: se entra al instante. Privado: un admin aprueba la solicitud.
- Las tareas que un integrante publica en el grupo quedan pendientes hasta que
  un admin las aprueba; las de los admins se aprueban solas.
- Cualquier admin nombra o quita admins y expulsa integrantes; al creador nadie lo toca.
"""
from django.db import transaction
from django.utils import timezone

from .models import CommunityGroupMember as Member
from .notifications import create_notification, retire_notification
from .signals import notify_task_tags_on_publish

PENDING = "pending"
APPROVED = "approved"
REJECTED = "rejected"


class GroupPermissionError(Exception):
    """La acción no está permitida; el mensaje se muestra tal cual."""


def membership(group, user):
    if not getattr(user, "is_authenticated", False):
        return None
    return Member.objects.filter(group=group, user=user).first()


def is_admin(group, user):
    member = membership(group, user)
    return bool(member and member.is_admin)


def active_admins(group):
    return Member.objects.filter(
        group=group, status=Member.STATUS_ACTIVE, role__in=Member.ADMIN_ROLES,
    ).select_related("user")


def _notify_admins(group, *, actor, notification_type, target_type, target_id, data, dedupe_key):
    for admin in active_admins(group):
        create_notification(
            recipient=admin.user,
            actor=actor,
            notification_type=notification_type,
            target_type=target_type,
            target_id=target_id,
            secondary_target_type="group",
            secondary_target_id=group.pk,
            data={"group_name": group.name, **data},
            dedupe_key=f"{dedupe_key}:{admin.user_id}",
        )


def create_group(*, user, **fields):
    with transaction.atomic():
        from .models import CommunityGroup

        group = CommunityGroup.objects.create(created_by=user, **fields)
        Member.objects.create(group=group, user=user, role=Member.ROLE_OWNER, status=Member.STATUS_ACTIVE)
    return group


def join(group, user):
    """Entra (público) o pide entrar (privado). Devuelve la membresía."""
    member, created = Member.objects.get_or_create(
        group=group, user=user,
        defaults={"status": Member.STATUS_PENDING if group.is_private else Member.STATUS_ACTIVE},
    )
    if created and member.status == Member.STATUS_PENDING:
        _notify_admins(
            group, actor=user, notification_type="group_join_request",
            target_type="group", target_id=group.pk, data={},
            dedupe_key=f"group_join_request:{member.pk}",
        )
    return member


def leave(group, user):
    member = membership(group, user)
    if not member:
        return
    if member.role == Member.ROLE_OWNER:
        raise GroupPermissionError("Eres el creador del grupo: no puedes salir. Puedes eliminar el grupo.")
    _retire_join_request(member)
    member.delete()


def hand_over_groups(user):
    """Antes de borrar una cuenta: cada grupo suyo pasa al admin o integrante más antiguo.

    Devuelve los grupos donde no queda nadie, que se van con la cuenta.
    """
    empty = []
    for owned in Member.objects.filter(user=user, role=Member.ROLE_OWNER).select_related("group"):
        others = Member.objects.filter(group=owned.group, status=Member.STATUS_ACTIVE).exclude(user=user)
        heir = others.filter(role=Member.ROLE_ADMIN).order_by("created_at").first() or others.order_by("created_at").first()
        if heir:
            heir.role = Member.ROLE_OWNER
            heir.save(update_fields=["role", "updated_at"])
        else:
            empty.append(owned.group)
    return empty


def _retire_join_request(member):
    for admin in active_admins(member.group):
        retire_notification(dedupe_key=f"group_join_request:{member.pk}:{admin.user_id}")


def _require_admin(group, actor):
    if not is_admin(group, actor):
        raise GroupPermissionError("Solo los admins del grupo pueden hacer esto.")


def approve_request(group, actor, member):
    _require_admin(group, actor)
    if member.status != Member.STATUS_PENDING:
        return member
    member.status = Member.STATUS_ACTIVE
    member.save(update_fields=["status", "updated_at"])
    _retire_join_request(member)
    create_notification(
        recipient=member.user, actor=actor, notification_type="group_join_approved",
        target_type="group", target_id=group.pk, data={"group_name": group.name},
        dedupe_key=f"group_join_approved:{member.pk}",
    )
    return member


def set_role(group, actor, member, role):
    """Cualquier admin nombra o quita admins. El creador no cambia de rol."""
    _require_admin(group, actor)
    if role not in (Member.ROLE_ADMIN, Member.ROLE_MEMBER):
        raise GroupPermissionError("El rol debe ser admin o integrante.")
    if member.role == Member.ROLE_OWNER:
        raise GroupPermissionError("Nadie puede cambiar el rol del creador del grupo.")
    if member.status != Member.STATUS_ACTIVE:
        raise GroupPermissionError("Primero acepta su solicitud para entrar al grupo.")
    if member.role == role:
        return member
    member.role = role
    member.save(update_fields=["role", "updated_at"])
    if role == Member.ROLE_ADMIN:
        create_notification(
            recipient=member.user, actor=actor, notification_type="group_admin",
            target_type="group", target_id=group.pk, data={"group_name": group.name},
            dedupe_key=f"group_admin:{member.pk}",
        )
    else:
        retire_notification(dedupe_key=f"group_admin:{member.pk}", recipient=member.user)
    return member


def remove_member(group, actor, member):
    """Expulsa a un integrante o rechaza su solicitud. A otros admins primero hay que quitarles el rol."""
    _require_admin(group, actor)
    if member.role == Member.ROLE_OWNER:
        raise GroupPermissionError("No se puede expulsar al creador del grupo.")
    if member.is_admin:
        raise GroupPermissionError("Primero quítale el rol de admin.")
    _retire_join_request(member)
    member.delete()


def submit_task(task, author):
    """Una tarea recién creada en un grupo: la de un admin se aprueba sola; la de un
    integrante queda pendiente y se avisa a los admins."""
    group = task.group
    member = membership(group, author)
    if not member or member.status != Member.STATUS_ACTIVE:
        raise GroupPermissionError("Únete al grupo para publicar en él.")
    if member.is_admin:
        task.group_status = APPROVED
        task.group_reviewed_by = author
        task.group_reviewed_at = timezone.now()
        task.save(update_fields=["group_status", "group_reviewed_by", "group_reviewed_at"])
        return task
    task.group_status = PENDING
    task.save(update_fields=["group_status"])
    _notify_admins(
        group, actor=author, notification_type="group_post_pending",
        target_type="task", target_id=task.pk, data={"task_title": (task.title or "")[:80]},
        dedupe_key=f"group_post_pending:{task.pk}",
    )
    return task


def review_task(task, actor, approve):
    group = task.group
    _require_admin(group, actor)
    if task.group_status != PENDING:
        raise GroupPermissionError("Esta publicación ya fue revisada.")
    task.group_status = APPROVED if approve else REJECTED
    task.group_reviewed_by = actor
    task.group_reviewed_at = timezone.now()
    task.save(update_fields=["group_status", "group_reviewed_by", "group_reviewed_at"])

    for admin in active_admins(group):
        retire_notification(dedupe_key=f"group_post_pending:{task.pk}:{admin.user_id}")
    create_notification(
        recipient=task.user, actor=actor,
        notification_type="group_post_approved" if approve else "group_post_rejected",
        target_type="task", target_id=task.pk,
        secondary_target_type="group", secondary_target_id=group.pk,
        data={"group_name": group.name, "task_title": (task.title or "")[:80]},
        dedupe_key=f"group_post_review:{task.pk}",
    )
    if approve:
        # Las etiquetas de una publicación pendiente se avisan hasta que se aprueba.
        notify_task_tags_on_publish(task)
    return task
