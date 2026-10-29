from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import models as ms
from . import task_saves
from .serializers import SimpleUserSerializer, file_to_abs_url, first_task_image
from .views import exclude_hidden_tasks, visible_tasks_for

User = get_user_model()

TOP_SIZE = 5


def _as_bool(value):
    return value in (True, 1, "1", "true", "True")


def _task_card(task, request):
    """Lo mínimo para mostrar una tarea del top 5 (mismo formato que `aportacion_info`)."""
    owner = task.user
    return {
        "id": str(task.id),
        "title": task.title,
        "image": file_to_abs_url(first_task_image(task), request),
        "pch": task.pch or None,
        "username": (owner.username if owner else None) or task.username or None,
    }


@api_view(["GET", "POST", "PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def task_save(request, task_id):
    """Guardar una tarea.

    GET: estado · POST: guardar (opcional `is_private`) · PATCH: cambiar `is_private`
    · DELETE: quitar de guardados (también de favoritos, del top 5 y de sus categorías).
    """
    if request.method == "POST":
        task = get_object_or_404(visible_tasks_for(request.user), id=task_id)
        is_private = _as_bool(request.data["is_private"]) if "is_private" in request.data else None
        created = not ms.TaskSave.objects.filter(user=request.user, task=task).exists()
        task_saves.save(request.user, task, is_private=is_private)
        return Response(
            task_saves.state(request.user, task),
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    # Lo que ya guardaste lo puedes manejar aunque la tarea se haya ocultado después.
    task = get_object_or_404(ms.Task, id=task_id)
    if request.method == "PATCH":
        if "is_private" not in request.data:
            return Response({"is_private": "Indica si es solo para ti."}, status=status.HTTP_400_BAD_REQUEST)
        if not ms.TaskSave.objects.filter(user=request.user, task=task).exists():
            return Response({"detail": "Primero guarda la tarea."}, status=status.HTTP_404_NOT_FOUND)
        task_saves.save(request.user, task, is_private=_as_bool(request.data["is_private"]))
    elif request.method == "DELETE":
        task_saves.unsave(request.user, task)
    return Response(task_saves.state(request.user, task))


@api_view(["POST", "PATCH"])
@permission_classes([IsAuthenticated])
def task_category_pin(request):
    """Top 5 por categoría.

    POST {task_id, category, is_pinned}: anclar (la agrega a favoritos) o desanclar.
    PATCH {category, order: [task_id, ...]}: nuevo orden de las ancladas en esa categoría.
    """
    if request.method == "PATCH":
        category = request.data.get("category")
        order = request.data.get("order")
        if not category or not isinstance(order, list):
            return Response({"order": "Envía la categoría y la lista de tareas."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            task_saves.reorder_category(request.user, category, order)
        except ValueError as error:
            return Response({"order": str(error)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"category": category, "order": [str(task_id) for task_id in order]})

    pinned = _as_bool(request.data.get("is_pinned", True))
    tasks = visible_tasks_for(request.user) if pinned else ms.Task.objects.all()
    task = get_object_or_404(tasks, id=request.data.get("task_id"))
    try:
        task_saves.pin_in_category(request.user, task, request.data.get("category"), pinned)
    except ValueError as error:
        return Response({"category": str(error)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(task_saves.state(request.user, task))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def favorites_top(request, user_id=None):
    """Top 5 para el perfil: perfiles anclados, tareas ancladas y el top 5 de cada categoría.

    Los demás ven cada parte solo si el dueño la tiene pública, y nunca sus guardadas
    "solo para mí" ni tareas que no pueden ver.
    """
    owner = get_object_or_404(User, id=user_id) if user_id else request.user
    is_owner = owner.pk == request.user.pk
    profile = ms.Profile.objects.get_or_create(user=owner)[0]
    payload = {
        "is_owner": is_owner,
        "visibility": {
            "profiles": bool(profile.favorite_profiles_public),
            "tasks": bool(profile.favorite_tasks_public),
        },
        "profiles": [],
        "tasks": [],
        "categories": [],
    }

    if is_owner or profile.favorite_profiles_public:
        pinned_profiles = (
            ms.pFavorito.objects.filter(user=owner, is_pinned=True)
            .select_related("perfil")
            .order_by("position", "created_at")[:TOP_SIZE]
        )
        payload["profiles"] = SimpleUserSerializer(
            [favorite.perfil for favorite in pinned_profiles], many=True, context={"request": request},
        ).data

    if is_owner or profile.favorite_tasks_public:
        private_ids = set() if is_owner else task_saves.private_task_ids(owner)
        favorites = exclude_hidden_tasks(
            ms.Favorito.objects.filter(user=owner), request.user, prefix="task__", viewer=request.user,
        ).exclude(task_id__in=private_ids)
        allowed = set(favorites.values_list("id", flat=True))
        pinned = list(favorites.filter(is_pinned=True).order_by("position", "created_at")[:TOP_SIZE])
        tops = {
            name: [favorite for favorite in top if favorite.id in allowed][:TOP_SIZE]
            for name, top in task_saves.category_tops(owner, exclude_task_ids=private_ids).items()
        }
        task_ids = {favorite.task_id for favorite in pinned}
        task_ids.update(favorite.task_id for top in tops.values() for favorite in top)
        cards = {
            task.pk: _task_card(task, request)
            for task in ms.Task.objects.filter(pk__in=task_ids).select_related("user")
            .prefetch_related("subtasks", "subfactores", "subfuentes")
        }
        payload["tasks"] = [cards[favorite.task_id] for favorite in pinned if favorite.task_id in cards]
        payload["categories"] = [
            {"name": name, "tasks": [cards[favorite.task_id] for favorite in top if favorite.task_id in cards]}
            for name, top in tops.items()
            if top
        ]
    return Response(payload)
