from django.utils import timezone
from django.db.models import Q
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
    GroupSerializer,
    GroupMembershipSerializer,
    GroupMessageSerializer,
)


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

        conversations_map = {}

        # ---------- 1) Conversaciones directas ----------
        direct_qs = (
            Message.objects
            .filter(Q(sender=user) | Q(receiver=user))
            .select_related('sender', 'receiver')
            .order_by('-timestamp')
        )

        for msg in direct_qs:
            other = msg.receiver if msg.sender == user else msg.sender
            key = f"direct-{other.id}"

            existing = conversations_map.get(key)
            if existing is None or existing["last_timestamp"] < msg.timestamp:
                other_image = UserSerializer(other, context={'request': request}).data.get('image')
                conversations_map[key] = {
                    "id": other.id,
                    "type": "direct",
                    "title": other.username,
                    "image": other_image,
                    "last_message": msg.content or "",
                    "last_timestamp": msg.timestamp,  # datetime
                }

        # ---------- 2) Conversaciones de grupo (vía GroupMembership) ----------
        group_ids = (
            GroupMembership.objects
            .filter(user=user)
            .values_list('group_id', flat=True)
        )
        group_qs = Group.objects.filter(id__in=group_ids).distinct()

        for group in group_qs:
            last_msg = (
                GroupMessage.objects
                .filter(group=group)
                .select_related('sender')
                .order_by('-timestamp')
                .first()
            )

            key = f"group-{group.id}"
            conversations_map[key] = {
                "id": group.id,
                "type": "group",
                "title": group.name,
                "last_message": last_msg.content if last_msg else "",
                "last_timestamp": last_msg.timestamp if last_msg else None,
            }

        # ---------- 3) Convertir a lista y ORDENAR ----------
        convs = list(conversations_map.values())

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
        page = int(request.query_params.get('page', 1))
        page_size = 10

        try:
            if user_id:
                messages = Message.objects.filter(
                    Q(sender_id=request.user.id, receiver_id=user_id) |
                    Q(sender_id=user_id, receiver_id=request.user.id)
                ).order_by('-timestamp')
            else:
                messages = Message.objects.all().order_by('-timestamp')

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
    name = request.data.get('name')
    if not name:
        return Response({'error': 'Group name is required'}, status=status.HTTP_400_BAD_REQUEST)

    group = Group.objects.create(name=name, created_by=request.user)
    GroupMembership.objects.create(user=request.user, group=group, is_admin=True)
    return Response(GroupSerializer(group).data, status=status.HTTP_201_CREATED)


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
    groups = Group.objects.filter(id__in=group_ids).distinct()
    serializer = GroupSerializer(groups, many=True, context={'request': request})
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def group_messages(request, group_id):
    group = get_object_or_404(Group, id=group_id)
    if not GroupMembership.objects.filter(group=group, user=request.user).exists():
        return Response({'error': 'You are not a member of this group'}, status=status.HTTP_403_FORBIDDEN)

    messages = GroupMessage.objects.filter(group=group).order_by('-timestamp')
    serializer = GroupMessageSerializer(messages, many=True, context={'request': request})
    return Response(serializer.data)

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
