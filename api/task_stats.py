"""Estadísticas de una publicación.

- Públicas (las ve quien pueda ver la publicación): me gusta, comentarios, impulsos,
  compartidas y cuántas veces la citaron (adjunta en comentarios, foro y compartidas).
- Para su creador (y staff): cuántas personas la guardaron, la pusieron en favoritos,
  la anclaron en su top 5 (general o de una categoría) y la compartieron en su historia.
"""
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import models as ms


def citation_counts(task):
    comments = ms.NewPeticionCommentPost.objects.filter(aportacion=task).count()
    forum = ms.Postt.objects.filter(aportacion=task).count()
    shared_comments = ms.SharedTaskComment.objects.filter(aportacion=task).count()
    return {
        "comments": comments,
        "forum": forum,
        "shared_comments": shared_comments,
        "total": comments + forum + shared_comments,
    }


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def task_stats(request, task_id):
    from .views import visible_tasks_for

    task = get_object_or_404(visible_tasks_for(request.user), pk=task_id)
    user = request.user
    is_owner = task.user_id == user.pk
    data = {
        "is_owner": is_owner,
        "public": {
            "likes": ms.Like.objects.filter(task=task).count(),
            "comments": ms.NewPeticionCommentPost.objects.filter(post=task).count(),
            "reposts": task.reposts.count(),
            "shares": task.share_count,
            "citations": citation_counts(task),
        },
        "private": None,
    }
    if is_owner or user.is_staff or user.is_superuser:
        data["private"] = {
            "saves": ms.TaskSave.objects.filter(task=task).count(),
            "favorites": ms.Favorito.objects.filter(task=task).count(),
            "pinned": ms.Favorito.objects.filter(task=task, is_pinned=True).count(),
            "category_pins": ms.TaskCategoryPin.objects.filter(favorite__task=task).count(),
            "story_shares": task.story_copies.count(),
        }
    return Response(data)
