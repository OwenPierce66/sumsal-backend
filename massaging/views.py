from django.utils import timezone
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Exists, OuterRef, Prefetch, Q
from django.shortcuts import get_object_or_404

from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.parsers import JSONParser, MultiPartParser, FormParser
from rest_framework import status

from django.contrib.auth import get_user_model
User = get_user_model()

from .models import (
    Message,
    MessageLike,
    MessageAttachment,
    Group,
    GroupMembership,
    GroupMessage,
    GroupMessageAttachment,
)
from .serializers import (
    UserSerializer,
    MessageSerializer,
    GroupCreateSerializer,
    GroupSerializer,
    GroupMembershipSerializer,
    GroupMessageSerializer,
)


def _sender_name(user):
    return user.username or f"{user.first_name} {user.last_name}".strip() or user.email


def _message_preview(message):
    content = (message.content or "").strip()
    if content:
        return content, "text"
    if message.image:
        return "Imagen", "image"
    if message.video:
        return "Video", "video"
    if getattr(message, "has_attachment", False):
        return "Archivo adjunto", "attachment"
    return "", "empty"


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_message(request, message_id):
    message = get_object_or_404(Message, id=message_id)

    # solo el que lo envió puede borrarlo
    if message.sender != request.user:
        return Response(
            {'error': 'Solo puedes borrar tus propios mensajes.'},
            status=status.HTTP_403_FORBIDDEN
        )

    message.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_group_message(request, message_id):
    message = get_object_or_404(GroupMessage, id=message_id)

    if message.sender != request.user:
        return Response(
            {'error': 'Solo puedes borrar tus propios mensajes.'},
            status=status.HTTP_403_FORBIDDEN
        )

    message.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def delete_group(request, group_id):
    group = get_object_or_404(Group, id=group_id)

    # Solo el creador puede borrar el grupo
    if group.created_by != request.user:
        return Response(
            {'error': 'Solo el creador del grupo puede eliminarlo.'},
            status=status.HTTP_403_FORBIDDEN
        )

    group.delete()
    return Response({'status': 'group deleted'}, status=status.HTTP_200_OK)


class UnifiedConversationsView(APIView):
    """
    Devuelve una lista combinada de conversaciones:
    - type = 'direct'  → chats directos con otros usuarios
    - type = 'group'   → grupos donde el usuario es miembro (vía GroupMembership)
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, format=None):
        user = request.user
        direct_qs = (
            Message.objects.annotate(
                has_attachment=Exists(
                    MessageAttachment.objects.filter(message_id=OuterRef("pk"))
                )
            )
            .filter(Q(sender=user) | Q(receiver=user))
            .select_related(
                "sender",
                "receiver",
                "sender__profile",
                "receiver__profile",
            )
            .order_by("-timestamp", "-id")
        )

        direct_conversations = {}
        for msg in direct_qs:
            other = msg.receiver if msg.sender_id == user.id else msg.sender
            conversation = direct_conversations.get(other.id)
            if conversation is None:
                preview, message_type = _message_preview(msg)
                other_image = UserSerializer(other, context={'request': request}).data.get('image')
                conversation = {
                    "id": other.id,
                    "type": "direct",
                    "title": _sender_name(other),
                    "image": other_image,
                    "last_message": preview,
                    "last_timestamp": msg.timestamp,
                    "last_sender_name": _sender_name(msg.sender),
                    "last_message_type": message_type,
                    "unread_count": 0,
                }
                direct_conversations[other.id] = conversation
            if msg.receiver_id == user.id and not msg.is_read:
                conversation["unread_count"] += 1

        memberships = list(
            GroupMembership.objects.filter(user=user).select_related(
                "group",
                "group__created_by",
            )
        )
        membership_by_group = {
            membership.group_id: membership for membership in memberships
        }
        group_ids = list(membership_by_group)
        member_counts = {
            row["group_id"]: row["member_count"]
            for row in (
                GroupMembership.objects.filter(group_id__in=group_ids)
                .values("group_id")
                .annotate(member_count=Count("id"))
            )
        }

        group_conversations = {}
        group_messages_qs = (
            GroupMessage.objects.annotate(
                has_attachment=Exists(
                    GroupMessageAttachment.objects.filter(message_id=OuterRef("pk"))
                )
            )
            .filter(group_id__in=group_ids)
            .select_related("sender")
            .order_by("-timestamp", "-id")
        )
        for msg in group_messages_qs:
            membership = membership_by_group[msg.group_id]
            conversation = group_conversations.get(msg.group_id)
            if conversation is None:
                preview, message_type = _message_preview(msg)
                conversation = {
                    "last_message": preview,
                    "last_timestamp": msg.timestamp,
                    "last_sender_name": _sender_name(msg.sender),
                    "last_message_type": message_type,
                    "unread_count": 0,
                }
                group_conversations[msg.group_id] = conversation
            if (
                msg.sender_id != user.id
                and (
                    membership.last_read_at is None
                    or msg.timestamp > membership.last_read_at
                )
            ):
                conversation["unread_count"] += 1

        convs = list(direct_conversations.values())
        for membership in memberships:
            group = membership.group
            activity = group_conversations.get(
                group.id,
                {
                    "last_message": "",
                    "last_timestamp": None,
                    "last_sender_name": None,
                    "last_message_type": "empty",
                    "unread_count": 0,
                },
            )
            convs.append(
                {
                    "id": group.id,
                    "type": "group",
                    "title": group.name,
                    "image": None,
                    **activity,
                    "member_count": member_counts.get(group.id, 0),
                    "created_by": group.created_by_id,
                    "current_user_is_admin": membership.is_admin,
                }
            )

        for c in convs:
            ts = c["last_timestamp"]
            if ts is None:
                c["_sort_ts"] = 0.0
            else:
                c["_sort_ts"] = ts.timestamp()

        convs.sort(key=lambda c: c["_sort_ts"], reverse=True)

        for c in convs:
            ts = c["last_timestamp"]
            c["last_timestamp"] = ts.isoformat() if ts else None
            c.pop("_sort_ts", None)

        return Response(convs)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def like_unlike_message(request, message_id):
    message = get_object_or_404(Message, id=message_id)
    like, created = MessageLike.objects.get_or_create(user=request.user, message=message)
    if not created:
        like.delete()
        return Response({'status': 'like removed'})
    return Response({'status': 'like added'})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def users_who_liked_message(request, message_id):
    message = get_object_or_404(Message, id=message_id)
    users = [like.user for like in message.likes.all()]
    serializer = UserSerializer(users, many=True)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def user_list(request):
    try:
        users = User.objects.all()
        serializer = UserSerializer(users, many=True, context={"request": request})
        return Response(serializer.data)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET', 'POST'])
@parser_classes([JSONParser, MultiPartParser, FormParser])
@permission_classes([IsAuthenticated])
def message_list(request):
    """
    GET  -> lista paginada de mensajes directos con otro usuario (user_id)
    POST -> crea un mensaje directo, soporta:
            - content
            - image / video
            - attachments[]
            - reply_to  (id del mensaje al que responde)
    """
    if request.method == 'GET':
        user_id = request.query_params.get('user_id')
        if not user_id:
            return Response(
                {"error": "user_id is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            other_user = User.objects.get(id=user_id)
        except (User.DoesNotExist, ValidationError, ValueError):
            return Response(
                {"error": "User not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            page = max(int(request.query_params.get('page', 1)), 1)
        except (TypeError, ValueError):
            return Response(
                {"error": "Invalid page"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        page_size = 10

        try:
            messages = Message.objects.filter(
                Q(sender=request.user, receiver=other_user)
                | Q(sender=other_user, receiver=request.user)
            ).order_by('-timestamp')

            Message.objects.filter(
                sender=other_user,
                receiver=request.user,
                is_read=False,
            ).update(is_read=True, read_at=timezone.now())

            start = (page - 1) * page_size
            end = start + page_size
            paginated_messages = messages[start:end]

            serializer = MessageSerializer(
                paginated_messages,
                many=True,
                context={'request': request}
            )
            return Response(serializer.data)
        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    # ================== POST ==================
    # Crear mensaje directo
    try:
        # 1) Validar receiver
        receiver_id = request.data.get('receiver')
        if not receiver_id:
            return Response(
                {"error": "Receiver ID is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        receiver = get_object_or_404(User, id=receiver_id)

        # 2) Datos simples
        content = request.data.get('content', '')

        # 3) Archivos individuales
        image = request.FILES.get('image')
        video = request.FILES.get('video')

        # 4) Mensaje al que responde (opcional)
        reply_to_id = request.data.get('reply_to')
        replied_to = None
        if reply_to_id:
            try:
                replied_to = Message.objects.get(id=reply_to_id)
            except Message.DoesNotExist:
                replied_to = None

        # 5) Crear el mensaje
        message = Message.objects.create(
            sender=request.user,
            receiver=receiver,
            content=content,
            image=image,
            video=video,
            replied_to=replied_to,
        )

        # 6) Adjuntos extra
        files = request.FILES.getlist('attachments')
        for f in files:
            ct = getattr(f, 'content_type', '') or ''
            MessageAttachment.objects.create(
                message=message,
                file=f,
                file_type=ct,
                is_image=ct.startswith('image/'),
                is_video=ct.startswith('video/'),
            )

        # 7) Serializar para salida
        out_serializer = MessageSerializer(
            message,
            context={'request': request}
        )
        return Response(out_serializer.data, status=status.HTTP_201_CREATED)

    except Exception as e:
        import traceback
        return Response(
            {"error": str(e), "traceback": traceback.format_exc()},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_group(request):
    serializer = GroupCreateSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    member_users = {
        member.id: member for member in serializer.validated_data.get("members", [])
    }
    member_users[request.user.id] = request.user

    with transaction.atomic():
        group = Group.objects.create(
            name=serializer.validated_data["name"],
            created_by=request.user,
        )
        GroupMembership.objects.bulk_create(
            [
                GroupMembership(
                    user=member,
                    group=group,
                    is_admin=member.id == request.user.id,
                )
                for member in member_users.values()
            ]
        )

    return Response(
        GroupSerializer(group, context={"request": request}).data,
        status=status.HTTP_201_CREATED,
    )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def add_member(request, group_id):
    group = get_object_or_404(Group, id=group_id)

    # 👉 creador o admin puede agregar
    is_creator = group.created_by_id == request.user.id
    is_admin = GroupMembership.objects.filter(
        group=group, user=request.user, is_admin=True
    ).exists()

    if not (is_creator or is_admin):
        return Response({'error': 'Only admins can add members'}, status=status.HTTP_403_FORBIDDEN)

    user_id = request.data.get('user_id')
    if not user_id:
        return Response({'error': 'user_id requerido'}, status=status.HTTP_400_BAD_REQUEST)

    user = get_object_or_404(User, id=user_id)
    GroupMembership.objects.get_or_create(user=user, group=group)
    return Response({'status': 'member added'}, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def remove_member(request, group_id):
    group = get_object_or_404(Group, id=group_id)

    # 👉 creador o admin puede eliminar
    is_creator = group.created_by_id == request.user.id
    is_admin = GroupMembership.objects.filter(
        group=group, user=request.user, is_admin=True
    ).exists()

    if not (is_creator or is_admin):
        return Response({'error': 'Only admins can remove members'}, status=status.HTTP_403_FORBIDDEN)

    user_id = request.data.get('user_id')
    if not user_id:
        return Response({'error': 'user_id requerido'}, status=status.HTTP_400_BAD_REQUEST)

    user = get_object_or_404(User, id=user_id)
    GroupMembership.objects.filter(user=user, group=group).delete()
    return Response({'status': 'member removed'}, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def make_admin(request, group_id):
    group = get_object_or_404(Group, id=group_id)

    # 👉 Puede hacer admin el creador o cualquier admin
    is_creator = group.created_by_id == request.user.id
    is_admin = GroupMembership.objects.filter(
        group=group,
        user=request.user,
        is_admin=True
    ).exists()

    if not (is_creator or is_admin):
        return Response(
            {'error': 'Solo administradores pueden hacer admin a otros.'},
            status=status.HTTP_403_FORBIDDEN
        )

    user_id = request.data.get('user_id')
    if not user_id:
        return Response(
            {'error': 'user_id requerido'},
            status=status.HTTP_400_BAD_REQUEST
        )

    user = get_object_or_404(User, id=user_id)

    membership, _ = GroupMembership.objects.get_or_create(
        user=user,
        group=group,
    )
    membership.is_admin = True
    membership.save()

    return Response(
        {'status': 'user promoted to admin'},
        status=status.HTTP_200_OK
    )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_groups(request):
    group_ids = (
        GroupMembership.objects
        .filter(user=request.user)
        .values_list('group_id', flat=True)
    )
    groups = Group.objects.filter(id__in=group_ids).prefetch_related(
        Prefetch(
            "groupmembership_set",
            queryset=GroupMembership.objects.select_related("user").order_by(
                "joined_at", "id"
            ),
            to_attr="prefetched_memberships",
        )
    ).distinct()
    serializer = GroupSerializer(groups, many=True, context={'request': request})
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def group_messages(request, group_id):
    group = get_object_or_404(Group, id=group_id)
    membership = GroupMembership.objects.filter(
        group=group,
        user=request.user,
    ).first()
    if membership is None:
        return Response({'error': 'You are not a member of this group'}, status=status.HTTP_403_FORBIDDEN)

    opened_at = timezone.now()
    messages = GroupMessage.objects.filter(
        group=group,
        timestamp__lte=opened_at,
    ).order_by('-timestamp')
    serializer = GroupMessageSerializer(messages, many=True, context={'request': request})
    data = serializer.data
    membership.last_read_at = opened_at
    membership.save(update_fields=["last_read_at"])
    return Response(data)

@api_view(['POST'])
@parser_classes([JSONParser, MultiPartParser, FormParser])
@permission_classes([IsAuthenticated])
def send_group_message(request, group_id):
    group = get_object_or_404(Group, id=group_id)
    if not GroupMembership.objects.filter(group=group, user=request.user).exists():
        return Response({'error': 'You are not a member of this group'}, status=status.HTTP_403_FORBIDDEN)

    content = request.data.get('content', '')

    image = request.FILES.get('image')
    video = request.FILES.get('video')

    # reply_to para mensajes de grupo
    reply_to_id = request.data.get('reply_to')
    replied_to = None
    if reply_to_id:
        try:
            replied_to = GroupMessage.objects.get(id=reply_to_id)
        except GroupMessage.DoesNotExist:
            replied_to = None

    message = GroupMessage.objects.create(
        group=group,
        sender=request.user,
        content=content,
        image=image,
        video=video,
        replied_to=replied_to,
    )

    files = request.FILES.getlist('attachments')
    for f in files:
        GroupMessageAttachment.objects.create(
            message=message,
            file=f,
            file_type=getattr(f, 'content_type', '') or '',
            is_image=(getattr(f, 'content_type', '') or '').startswith('image/'),
            is_video=(getattr(f, 'content_type', '') or '').startswith('video/'),
        )

    serializer = GroupMessageSerializer(message, context={'request': request})
    return Response(serializer.data, status=status.HTTP_201_CREATED)
