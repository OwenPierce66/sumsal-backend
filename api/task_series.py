"""Series: anterior y siguiente recomendado.

Cada publicación puede guardar cuál recomienda ver antes (`previous_task`) y después
(`next_task`). Los enlaces van en los dos sentidos:
- Si una no eligió su siguiente, su siguiente es la que la eligió como anterior (y al revés).
- Cuando el autor enlaza dos publicaciones suyas, se guarda en las dos; al quitarlo,
  se quita en las dos (`sync_series_links`).
La serie completa se arma recorriendo esos enlaces desde la publicación.
"""
from django.db.models import Case, IntegerField, Value, When

from . import models as ms

MAX_SERIES_STEPS = 12


def _derived(visible, field, task):
    """La que apunta a `task` por `field`; primero una del mismo autor y la más reciente."""
    return visible.filter(**{field: task}).select_related("user").annotate(
        same_author=Case(When(user_id=task.user_id, then=Value(0)), default=Value(1), output_field=IntegerField()),
    ).order_by("same_author", "-created_at").first()


def _resolve(task, visible, own_field, back_field):
    own_id = getattr(task, f"{own_field}_id")
    if own_id:
        chosen = visible.filter(pk=own_id).select_related("user").first()
        if chosen:
            return chosen, True
    derived = _derived(visible, back_field, task)
    return derived, False


def resolve_next(task, visible):
    """(siguiente, la eligió su autor)."""
    return _resolve(task, visible, "next_task", "previous_task")


def resolve_previous(task, visible):
    """(anterior, la eligió su autor)."""
    return _resolve(task, visible, "previous_task", "next_task")


def series_of(task, visible):
    """Todas las partes en orden, recorriendo anterior y siguiente desde `task`."""
    seen = {task.pk}
    before = []
    current = task
    for _ in range(MAX_SERIES_STEPS):
        previous, _chosen = resolve_previous(current, visible)
        if previous is None or previous.pk in seen:
            break
        seen.add(previous.pk)
        before.append(previous)
        current = previous
    after = []
    current = task
    for _ in range(MAX_SERIES_STEPS):
        following, _chosen = resolve_next(current, visible)
        if following is None or following.pk in seen:
            break
        seen.add(following.pk)
        after.append(following)
        current = following
    return list(reversed(before)) + [task] + after


def sync_series_links(task, before_next_id=None, before_previous_id=None):
    """Lo que el autor cambió en `task` se refleja en la otra publicación si también es suya."""
    own = ms.Task.objects.filter(user_id=task.user_id)
    if task.next_task_id != before_next_id:
        if before_next_id:
            own.filter(pk=before_next_id, previous_task=task).update(previous_task=None)
        if task.next_task_id:
            own.filter(pk=task.next_task_id, previous_task__isnull=True).update(previous_task=task)
    if task.previous_task_id != before_previous_id:
        if before_previous_id:
            own.filter(pk=before_previous_id, next_task=task).update(next_task=None)
        if task.previous_task_id:
            own.filter(pk=task.previous_task_id, next_task__isnull=True).update(next_task=task)
