"""
Tareas guardadas: Guardar -> Favorito -> Top 5 (general y por categoría).

Es la misma escala que Seguir -> Favorito -> Anclado de los perfiles:
- Guardar (TaskSave) es la base. Cada guardada puede ser "solo para mí" (`is_private`).
- Favorito (Favorito) es una guardada que además es favorita; agregar a favoritos la guarda.
- Top 5 general: `Favorito.is_pinned` (ver `toggle_favorite_pin` en views.py).
- Top 5 por categoría (TaskCategoryPin): hasta 5 favoritas ancladas en cada categoría.

Quitar de guardados quita el favorito, el top 5 y los anclajes por categoría (signals.py).
Los demás ven las guardadas de alguien solo si las tiene públicas y nunca las "solo para mí".
"""
from django.db import transaction

from . import models as ms
from .notifications import create_notification

APPROVAL_ALIASES = {"aprobada", "aprobadas", "aprovada", "aprovadas"}


def task_categories(task):
    """Categorías de la tarea que admiten top 5 (sin las etiquetas de estado como "Procesando")."""
    seen = set()
    names = []
    for raw in str(task.categories or "").split(","):
        name = raw.strip()
        key = name.casefold()
        if not name or key in seen or key in ms.STATUS_TAGS or key in APPROVAL_ALIASES:
            continue
        seen.add(key)
        names.append(name)
    return names


def match_category(task, category):
    """La categoría tal como la escribe la tarea, o None si la tarea no la tiene."""
    key = str(category or "").strip().casefold()
    return next((name for name in task_categories(task) if name.casefold() == key), None)


def save(user, task, is_private=None):
    """Guarda la tarea (o solo cambia si es "solo para mí" si ya estaba guardada)."""
    saved, created = ms.TaskSave.objects.get_or_create(
        user=user, task=task, defaults={"is_private": bool(is_private)},
    )
    if not created and is_private is not None and saved.is_private != bool(is_private):
        saved.is_private = bool(is_private)
        saved.save(update_fields=["is_private"])
    return saved


def unsave(user, task):
    """Quitar de guardados; el signal quita también el favorito y sus anclajes."""
    ms.TaskSave.objects.filter(user=user, task=task).delete()


def pin_in_category(user, task, category, pinned):
    """Ancla o desancla la tarea en el top 5 de una de sus categorías.

    Anclar la agrega a favoritos (y a guardados). Si la categoría ya tiene 5, la quinta
    sale para hacerle lugar, igual que en el top 5 general. Devuelve el nombre de la categoría.
    """
    name = match_category(task, category)
    if not name:
        raise ValueError("La tarea no tiene esa categoría.")
    with transaction.atomic():
        if not pinned:
            ms.TaskCategoryPin.objects.filter(
                favorite__user=user, favorite__task=task, category__iexact=name,
            ).delete()
            _renumber(user, name)
            return name

        favorite, _ = ms.Favorito.objects.get_or_create(user=user, task=task)
        if ms.TaskCategoryPin.objects.filter(favorite=favorite, category__iexact=name).exists():
            return name
        others = list(
            ms.TaskCategoryPin.objects.select_for_update()
            .filter(favorite__user=user, category__iexact=name)
            .order_by("position", "created_at", "pk")
        )
        keep = others[: ms.TaskCategoryPin.MAX_PER_CATEGORY - 1]
        ms.TaskCategoryPin.objects.filter(pk__in=[pin.pk for pin in others[len(keep):]]).delete()
        for position, pin in enumerate(keep):
            if pin.position != position:
                pin.position = position
                pin.save(update_fields=["position"])
        ms.TaskCategoryPin.objects.create(favorite=favorite, category=name, position=len(keep))

    create_notification(
        recipient=task.user,
        actor=user,
        notification_type="favorite_pin",
        target_type="task",
        target_id=task.pk,
        data={"text": f"{user.username or 'Alguien'} colocó tu tarea entre sus 5 favoritas de {name}.", "category": name},
        dedupe_key=f"favorite_pin:{user.pk}:task:{task.pk}:category:{name.casefold()}",
    )
    return name


def reorder_category(user, category, task_ids):
    """Nuevo orden del top 5 de una categoría (lista con todas sus tareas ancladas)."""
    key = str(category or "").strip()
    pins = {
        str(pin.favorite.task_id): pin
        for pin in ms.TaskCategoryPin.objects.select_related("favorite")
        .filter(favorite__user=user, category__iexact=key)
    }
    order = [str(task_id) for task_id in task_ids]
    if sorted(order) != sorted(pins):
        raise ValueError("La lista debe tener todas las tareas ancladas en la categoría una sola vez.")
    with transaction.atomic():
        for position, task_id in enumerate(order):
            pin = pins[task_id]
            if pin.position != position:
                pin.position = position
                pin.save(update_fields=["position"])


def _renumber(user, category):
    for position, pin in enumerate(
        ms.TaskCategoryPin.objects.filter(favorite__user=user, category__iexact=category)
        .order_by("position", "created_at", "pk")
    ):
        if pin.position != position:
            pin.position = position
            pin.save(update_fields=["position"])


def state(user, task):
    """Relación de `user` con la tarea, para responder después de cada cambio."""
    saved = ms.TaskSave.objects.filter(user=user, task=task).first()
    favorite = ms.Favorito.objects.filter(user=user, task=task).first()
    return {
        "task_id": str(task.pk),
        "saved": saved is not None,
        "is_private": bool(saved and saved.is_private),
        "favorite": favorite is not None,
        "pinned": bool(favorite and favorite.is_pinned),
        "pinned_categories": (
            list(favorite.category_pins.order_by("category").values_list("category", flat=True))
            if favorite else []
        ),
        "categories": task_categories(task),
    }


def visible_saves(owner, viewer):
    """Guardadas de `owner` que puede ver `viewer` (el dueño ve también las "solo para mí")."""
    saves = ms.TaskSave.objects.filter(user=owner)
    if getattr(viewer, "pk", None) != owner.pk:
        saves = saves.filter(is_private=False)
    return saves


def private_task_ids(owner):
    return set(
        ms.TaskSave.objects.filter(user=owner, is_private=True).values_list("task_id", flat=True)
    )


def category_tops(owner, *, exclude_task_ids=()):
    """Top 5 por categoría: {categoría: [Favorito, ...]} en orden, sin las tareas excluidas."""
    tops = {}
    names = {}
    pins = (
        ms.TaskCategoryPin.objects.filter(favorite__user=owner)
        .exclude(favorite__task_id__in=list(exclude_task_ids))
        .select_related("favorite")
        .order_by("position", "created_at", "pk")
    )
    for pin in pins:
        key = pin.category.casefold()
        names.setdefault(key, pin.category)
        tops.setdefault(key, []).append(pin.favorite)
    return {names[key]: favorites for key, favorites in sorted(tops.items())}
