from django.db.models import Count, OuterRef, Q, Subquery
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import community_groups as groups
from .group_serializers import CommunityGroupMemberSerializer, CommunityGroupSerializer
from .models import CommunityGroup, CommunityGroupMember as Member, Task
from .serializers import TaskSerializer
from .views import TASK_SERIALIZER_PREFETCH, StandardPagination, exclude_hidden_tasks, filter_by_category_path

_PRIVATE = {"detail": "Este grupo es privado: solo sus integrantes ven lo que se publica."}


def _groups_for(user):
    """Grupos con su número de integrantes y el rol/estado de `user` en cada uno."""
    mine = Member.objects.filter(group=OuterRef("pk"), user=user)
    return CommunityGroup.objects.select_related("created_by").annotate(
        members_count=Count("memberships", filter=Q(memberships__status=Member.STATUS_ACTIVE), distinct=True),
        my_role=Subquery(mine.values("role")[:1]),
        my_status=Subquery(mine.values("status")[:1]),
    )


def _group_or_404(request, group_id):
    return get_object_or_404(_groups_for(request.user), pk=group_id)


def _is_active_member(group):
    return group.my_status == Member.STATUS_ACTIVE


def _detail(group, request):
    data = CommunityGroupSerializer(group, context={"request": request}).data
    admins = groups.active_admins(group).prefetch_related("user__fixed_images").order_by("created_at")
    data["admins"] = CommunityGroupMemberSerializer(admins, many=True, context={"request": request}).data
    if data["is_admin"]:
        data["pending_posts_count"] = group.tasks.filter(group_status=groups.PENDING).count()
        data["pending_requests_count"] = group.memberships.filter(status=Member.STATUS_PENDING).count()
    else:
        data["my_pending_posts_count"] = group.tasks.filter(
            group_status=groups.PENDING, user=request.user,
        ).count()
    return data


def _permission_error(error):
    return Response({"detail": str(error)}, status=status.HTTP_403_FORBIDDEN)


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser, JSONParser])
def group_list_create(request):
    """GET: ?mine=1 (mis grupos) y ?q= (buscar por nombre o descripción). POST: crea un grupo."""
    if request.method == "POST":
        serializer = CommunityGroupSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        group = groups.create_group(user=request.user, **serializer.validated_data)
        return Response(_detail(_group_or_404(request, group.pk), request), status=status.HTTP_201_CREATED)

    queryset = _groups_for(request.user)
    if request.query_params.get("mine") in ("1", "true"):
        queryset = queryset.filter(memberships__user=request.user, memberships__status=Member.STATUS_ACTIVE)
    query = " ".join(str(request.query_params.get("q") or "").split())
    if query:
        queryset = queryset.filter(Q(name__icontains=query) | Q(description__icontains=query))
    queryset = queryset.order_by("-members_count", "-created_at")[:50]
    return Response(CommunityGroupSerializer(queryset, many=True, context={"request": request}).data)


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser, JSONParser])
def group_detail(request, group_id):
    group = _group_or_404(request, group_id)
    if request.method == "GET":
        return Response(_detail(group, request))

    if request.method == "DELETE":
        if group.my_role != Member.ROLE_OWNER and not request.user.is_superuser:
            return Response({"detail": "Solo el creador puede eliminar el grupo."}, status=status.HTTP_403_FORBIDDEN)
        group.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    if not (group.my_status == Member.STATUS_ACTIVE and group.my_role in Member.ADMIN_ROLES):
        return Response({"detail": "Solo los admins pueden editar el grupo."}, status=status.HTTP_403_FORBIDDEN)
    serializer = CommunityGroupSerializer(group, data=request.data, partial=True, context={"request": request})
    serializer.is_valid(raise_exception=True)
    serializer.save()
    return Response(_detail(_group_or_404(request, group_id), request))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def group_join(request, group_id):
    group = _group_or_404(request, group_id)
    groups.join(group, request.user)
    return Response(_detail(_group_or_404(request, group_id), request))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def group_leave(request, group_id):
    group = _group_or_404(request, group_id)
    try:
        groups.leave(group, request.user)
    except groups.GroupPermissionError as error:
        return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(_detail(_group_or_404(request, group_id), request))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def group_members(request, group_id):
    """Integrantes activos (admins primero). ?status=pending: solicitudes, solo para admins."""
    group = _group_or_404(request, group_id)
    is_admin = groups.is_admin(group, request.user)
    if group.is_private and not _is_active_member(group):
        return Response(_PRIVATE, status=status.HTTP_403_FORBIDDEN)
    wanted = request.query_params.get("status") or Member.STATUS_ACTIVE
    if wanted == Member.STATUS_PENDING and not is_admin:
        return Response({"detail": "Solo los admins ven las solicitudes."}, status=status.HTTP_403_FORBIDDEN)
    members = (
        group.memberships.filter(status=wanted)
        .select_related("user")
        .prefetch_related("user__fixed_images")
        .order_by("created_at")
    )
    rank = {Member.ROLE_OWNER: 0, Member.ROLE_ADMIN: 1, Member.ROLE_MEMBER: 2}
    members = sorted(members, key=lambda m: rank.get(m.role, 3))
    return Response(CommunityGroupMemberSerializer(members, many=True, context={"request": request}).data)


@api_view(["PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def group_member_detail(request, group_id, user_id):
    """PATCH {"status": "active"} acepta una solicitud; {"role": "admin"|"member"} cambia el rol.
    DELETE expulsa a un integrante o rechaza su solicitud."""
    group = _group_or_404(request, group_id)
    member = get_object_or_404(Member.objects.select_related("user"), group=group, user_id=user_id)
    try:
        if request.method == "DELETE":
            groups.remove_member(group, request.user, member)
            return Response(status=status.HTTP_204_NO_CONTENT)
        if request.data.get("status") == Member.STATUS_ACTIVE:
            member = groups.approve_request(group, request.user, member)
        if "role" in request.data:
            member = groups.set_role(group, request.user, member, request.data.get("role"))
    except groups.GroupPermissionError as error:
        return _permission_error(error)
    return Response(CommunityGroupMemberSerializer(member, context={"request": request}).data)


def _task_page(request, queryset):
    paginator = StandardPagination()
    page = paginator.paginate_queryset(
        queryset.select_related("user", "group").prefetch_related(*TASK_SERIALIZER_PREFETCH), request,
    )
    data = TaskSerializer(page, many=True, context={"request": request}).data
    return paginator.get_paginated_response(data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def group_tasks(request, group_id):
    """Publicaciones aprobadas del grupo, de la más nueva a la más vieja."""
    group = _group_or_404(request, group_id)
    if group.is_private and not _is_active_member(group):
        return Response(_PRIVATE, status=status.HTTP_403_FORBIDDEN)
    queryset = exclude_hidden_tasks(
        Task.objects.filter(group=group, group_status=groups.APPROVED), viewer=request.user,
    ).order_by("-created_at")
    # Filtro por categoría y subcategorías, como el feed.
    return _task_page(request, filter_by_category_path(queryset, request.query_params.get("category")))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def group_pending_tasks(request, group_id):
    """Admins: todo lo que espera revisión. Integrantes: lo suyo pendiente o rechazado."""
    group = _group_or_404(request, group_id)
    if groups.is_admin(group, request.user):
        queryset = Task.objects.filter(group=group, group_status=groups.PENDING).order_by("created_at")
    elif _is_active_member(group):
        queryset = Task.objects.filter(
            group=group, user=request.user, group_status__in=[groups.PENDING, groups.REJECTED],
        ).order_by("-created_at")
    else:
        return Response({"detail": "Únete al grupo para ver tus publicaciones pendientes."}, status=status.HTTP_403_FORBIDDEN)
    return _task_page(request, queryset)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def group_task_review(request, group_id, task_id):
    """{"approve": true|false}: un admin aprueba o rechaza una publicación pendiente."""
    group = _group_or_404(request, group_id)
    task = get_object_or_404(Task.objects.select_related("user", "group"), pk=task_id, group=group)
    approve = request.data.get("approve")
    if not isinstance(approve, bool):
        return Response({"approve": ["Debe ser true o false."]}, status=status.HTTP_400_BAD_REQUEST)
    try:
        task = groups.review_task(task, request.user, approve)
    except groups.GroupPermissionError as error:
        return _permission_error(error)
    return Response(TaskSerializer(task, context={"request": request}).data)
