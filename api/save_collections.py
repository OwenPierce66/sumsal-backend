"""Colecciones (álbumes) propias dentro de guardados.

Una colección agrupa tareas guardadas. Agregar una tarea a una colección la guarda si
faltaba; quitarla de guardados la saca de todas sus colecciones. Los demás solo ven las
colecciones públicas y, dentro, las guardadas que no son "solo para mí".
"""
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import models as ms
from . import task_saves

User = get_user_model()
DUPLICATE_NAME = "Ya tienes una colección con ese nombre."


def _clean_name(raw):
    return " ".join(str(raw or "").split())[: ms.SaveCollection.MAX_NAME_LENGTH]


def _task_data(task):
    return {
        "id": str(task.pk),
        "title": task.title,
        "pch": task.pch,
        "categories": task.categories,
        "user": {"id": str(task.user_id), "username": task.user.username if task.user else ""},
    }


def _visible_items(collection, viewer):
    from .views import exclude_hidden_tasks

    items = collection.items.select_related("saved__task__user")
    if getattr(viewer, "pk", None) != collection.user_id:
        items = items.filter(saved__is_private=False)
    visible = exclude_hidden_tasks(ms.Task.objects.all(), viewer=viewer)
    return items.filter(saved__task__in=visible)


def _summary(collection, viewer):
    return {
        "id": str(collection.pk),
        "name": collection.name,
        "is_private": collection.is_private,
        "count": _visible_items(collection, viewer).count(),
        "created_at": collection.created_at,
    }


def _detail(collection, viewer):
    data = _summary(collection, viewer)
    data["is_owner"] = getattr(viewer, "pk", None) == collection.user_id
    data["items"] = [
        {"id": item.pk, "added_at": item.created_at, "is_private": item.saved.is_private, "task": _task_data(item.saved.task)}
        for item in _visible_items(collection, viewer)
    ]
    return data


def _apply_changes(collection, data):
    fields = []
    if "name" in data:
        name = _clean_name(data.get("name"))
        if not name:
            return {"name": ["Escribe un nombre."]}
        collection.name = name
        fields.append("name")
    if "is_private" in data:
        if not isinstance(data.get("is_private"), bool):
            return {"is_private": ["Debe ser verdadero o falso."]}
        collection.is_private = data["is_private"]
        fields.append("is_private")
    return fields


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def my_collections(request):
    """GET: mis colecciones. POST {name, is_private?}: crear una."""
    if request.method == "GET":
        collections = ms.SaveCollection.objects.filter(user=request.user)
        return Response([_summary(item, request.user) for item in collections])

    if ms.SaveCollection.objects.filter(user=request.user).count() >= ms.SaveCollection.MAX_PER_USER:
        return Response(
            {"detail": f"Puedes tener hasta {ms.SaveCollection.MAX_PER_USER} colecciones."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    collection = ms.SaveCollection(user=request.user, position=ms.SaveCollection.objects.filter(user=request.user).count())
    result = _apply_changes(collection, {"is_private": True, **request.data, "name": request.data.get("name")})
    if isinstance(result, dict):
        return Response(result, status=status.HTTP_400_BAD_REQUEST)
    try:
        with transaction.atomic():
            collection.save()
    except IntegrityError:
        return Response({"name": [DUPLICATE_NAME]}, status=status.HTTP_400_BAD_REQUEST)
    return Response(_summary(collection, request.user), status=status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def user_collections(request, user_id):
    """Colecciones de otra persona: solo las públicas (el dueño ve todas)."""
    owner = get_object_or_404(User, pk=user_id)
    collections = ms.SaveCollection.objects.filter(user=owner)
    if owner.pk != request.user.pk:
        collections = collections.filter(is_private=False)
    return Response([_summary(item, request.user) for item in collections])


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def collection_detail(request, collection_id):
    """GET: la colección con sus tareas. PATCH {name?, is_private?} y DELETE: solo su dueño."""
    collection = get_object_or_404(ms.SaveCollection.objects.select_related("user"), pk=collection_id)
    is_owner = collection.user_id == request.user.pk
    if request.method == "GET":
        if collection.is_private and not is_owner:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(_detail(collection, request.user))
    if not is_owner:
        return Response(status=status.HTTP_404_NOT_FOUND)
    if request.method == "DELETE":
        collection.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    result = _apply_changes(collection, request.data)
    if isinstance(result, dict):
        return Response(result, status=status.HTTP_400_BAD_REQUEST)
    try:
        with transaction.atomic():
            collection.save(update_fields=result or None)
    except IntegrityError:
        return Response({"name": [DUPLICATE_NAME]}, status=status.HTTP_400_BAD_REQUEST)
    return Response(_summary(collection, request.user))


@api_view(["POST", "DELETE"])
@permission_classes([IsAuthenticated])
def collection_item(request, collection_id, task_id=None):
    """POST {task_id}: agregar (la guarda si faltaba). DELETE .../<task_id>/: quitarla de la colección."""
    from .views import visible_tasks_for

    collection = get_object_or_404(ms.SaveCollection, pk=collection_id, user=request.user)
    target_id = task_id or request.data.get("task_id")
    if request.method == "DELETE":
        collection.items.filter(saved__task_id=target_id).delete()
        return Response(_summary(collection, request.user))
    task = get_object_or_404(visible_tasks_for(request.user), pk=target_id)
    with transaction.atomic():
        saved = task_saves.save(request.user, task)
        ms.SaveCollectionItem.objects.get_or_create(collection=collection, saved=saved)
    return Response(_summary(collection, request.user), status=status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def task_collections(request, task_id):
    """Mis colecciones, marcando en cuáles está esta tarea (para el selector)."""
    inside = set(
        ms.SaveCollectionItem.objects.filter(
            collection__user=request.user, saved__task_id=task_id,
        ).values_list("collection_id", flat=True)
    )
    return Response([
        {**_summary(item, request.user), "contains": item.pk in inside}
        for item in ms.SaveCollection.objects.filter(user=request.user)
    ])
