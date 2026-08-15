from django.urls import path
from . import views
from . import notification_views
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)

urlpatterns = [
    # Notificaciones
    path('notifications/', notification_views.NotificationListView.as_view(), name='notification-list'),
    path('notifications/unread-count/', notification_views.unread_count, name='notification-unread-count'),
    path('notifications/mark-all-read/', notification_views.mark_all_read, name='notification-mark-all-read'),
    path('notifications/<uuid:notification_id>/mark-read/', notification_views.mark_read, name='notification-mark-read'),
    path('notifications/<uuid:notification_id>/', notification_views.delete_notification, name='notification-delete'),

    # Autenticación y Usuarios
    path('auth/register/', views.RegisterView.as_view(), name='register'),
    # ✅ FIX: Usar las vistas correctas de simplejwt y eliminar duplicados
    path('auth/login/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('auth/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('users/me/', views.UserMeView.as_view(), name='user-me'),
    path('users/me/tasks/', views.UserMyTasksView.as_view(), name='user-my-tasks'),
    path('users/<uuid:user_id>/portadas/', views.obtener_portadas_usuario, name='user-portadas'),
    path('users/<uuid:user_id>/imagen-fija/', views.obtener_imagen_fija_usuario, name='user-imagen-fija'),
    path('user-details/', views.get_user_details, name='user-details'),
    path('profile/', views.get_current_user_profile, name='user-profile'),
    path('massaging/users/', views.list_users, name='list-users'),

    # Tareas (Reels) y Feed
    path('tasks/', views.TaskListCreateView.as_view(), name='task-list-create'),
    path('stories/', views.StoryListCreateView.as_view(), name='story-list-create'),
    path('stories/share-task/', views.share_task_to_story, name='story-share-task'),
    path('feed/', views.FeedView.as_view(), name='feed'),
    path('tasks/<uuid:id>/', views.TaskDetailView.as_view(), name='task-detail'),
    path('tasks/<uuid:task_id>/like/', views.toggle_task_like, name='task-like'),
    path('tasks/<uuid:task_id>/repost/', views.repost_task, name='task-repost'), # ✅ ¡AQUÍ ESTÁ!
    path('tasks/<uuid:task_id>/users-who-liked/', views.users_who_liked_task, name='task-likers'),
    path('tasks/<uuid:task_id>/users-who-shared/', views.users_who_shared_task, name='task-sharers'),

    # Comentarios de Tareas
    path('tasks/<uuid:task_id>/comments/', views.TaskCommentListCreateView.as_view(), name='task-comments'),
    path('comments/<int:comment_id>/', views.NewPeticionCommentDetailsView.as_view(), name='task-comment-detail'),
    path('comments/<int:comment_id>/like/', views.toggle_comment_like, name='comment-like'),
    path('comments/<int:comment_id>/users-who-liked/', views.users_who_liked_comment, name='comment-likers'),

    # Tareas Compartidas (Legado, para TasksScreen)
    path('shared-tasks/', views.SharedTaskListCreateView.as_view(), name='shared-task-list-create'),
    path('shared-tasks/<uuid:id>/', views.SharedTaskDetailView.as_view(), name='shared-task-detail'),
    path('shared-tasks/<uuid:shared_task_id>/like/', views.toggle_shared_task_like, name='shared-task-like'),
    path('shared-tasks/<uuid:shared_task_id>/users-who-liked/', views.users_who_liked_shared_task, name='shared-task-likers'),
    path('shared-tasks/<uuid:shared_task_id>/comments/', views.SharedTaskCommentListCreateView.as_view(), name='shared-task-comments'),
    path('shared-tasks/<uuid:shared_task_id>/comments/<int:comment_id>/', views.SharedTaskCommentDetailsView.as_view(), name='shared-task-comment-detail'),
    path('shared-tasks/<uuid:shared_task_id>/comments/<int:comment_id>/like/', views.toggle_shared_task_comment_like, name='shared-task-comment-like'),
    path('shared-tasks/comments/<int:comment_id>/users-who-liked/', views.users_who_liked_shared_comment, name='shared-task-comment-likers'),

    # Perfiles y Likes de Perfil
    path('profiles/<uuid:profile_id>/like/', views.like_unlike_profile, name='profile-like'),
    path('profiles/<uuid:profile_id>/likes/', views.list_likes, name='profile-likers'),

    # Favoritos
    path('favoritos/agregar/', views.agregar_favorito, name='favorito-add'),
    path('favoritos/listar/', views.listar_favoritos, name='favorito-list'),
    path('favoritos/listar/<uuid:user_id>/', views.listar_favoritos, name='favorito-list-user'),
    path('pfavoritos/agregar/', views.agregar_pfavorito, name='pfavorito-add'),
    path('pfavoritos/listar/', views.listar_pfavoritos, name='pfavorito-list'),
    path('pfavoritos/listar/<uuid:user_id>/', views.listar_pfavoritos, name='pfavorito-list-user'),

    # Categorías
    path('categories/', views.create_categoryp, name='category-p-list-create'),
    path('new-categories/', views.new_category_list_create, name='new-category-list-create'),

    # Admin
    path('verify-admin/', views.verify_admin, name='verify-admin'), # FIX: Movido para que coincida con el frontend
    path('admin/users/<uuid:user_id>/verify/', views.admin_verify_user, name='admin-verify-user'),
    path('admin/users/<uuid:user_id>/recommend/', views.admin_recommend_user, name='admin-recommend-user'),
    path('admin/tasks/<uuid:task_id>/like/', views.admin_app_like_task, name='admin-task-like'),
    path('admin/profiles/<uuid:profile_id>/like/', views.admin_app_like_profile, name='admin-profile-like'),
]