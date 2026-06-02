from django.urls import path
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)

from . import views as vs
from .throttling import LoginThrottle, RefreshThrottle

urlpatterns = [
    # ========== AUTENTICACIÓN (Sumsal Sync) ==========
    path("auth/register/", vs.RegisterView.as_view(), name="register"),
    path(
        "auth/login/",
        TokenObtainPairView.as_view(throttle_classes=[LoginThrottle]),
        name="login",
    ),
    path(
        "auth/refresh/",
        TokenRefreshView.as_view(throttle_classes=[RefreshThrottle]),
        name="token_refresh",
    ),
    path("users/me/", vs.UserMeView.as_view(), name="user-me"),
    path("users/me/tasks/", vs.UserMyTasksView.as_view(), name="user-my-tasks"),

    # ========== USUARIOS (Uso de UUID para seguridad) ==========    path("users/", vs.list_users, name="list-users"),
    path("users/<uuid:user_id>/portadas/", vs.obtener_portadas_usuario, name="user-portadas"),
    path("users/<uuid:user_id>/imagen-fija/", vs.obtener_imagen_fija_usuario, name="user-imagen-fija"),
    path("user-details/", vs.get_user_details, name="user-details"),
    path("profile/", vs.get_current_user_profile, name="user-profile"),
    
    # ========== TAREAS / PETICIONES ==========
    path("tasks/", vs.TaskListCreateView.as_view(), name="task-list-create"),
    path("tasks/<int:id>/", vs.TaskDetailView.as_view(), name="task-detail"),
    path("tasks/<int:task_id>/like/", vs.toggle_task_like, name="task-like"),
    path("tasks/<int:task_id>/users-who-liked/", vs.users_who_liked_task, name="users-who-liked"),
    
    # ========== COMENTARIOS (Hilos anidados) ==========
    path("tasks/<int:task_id>/comments/", vs.TaskCommentListCreateView.as_view(), name="task-comments"),
    
    # ⚡ LA LÍNEA MÁGICA PARA BORRAR Y EDITAR COMENTARIOS
    path("tasks/<int:task_id>/comments/<int:comment_id>/", vs.NewPeticionCommentDetailsView.as_view(), name="task-comment-detail"),
    
    path("comments/<int:comment_id>/like/", vs.toggle_comment_like, name="comment-like"),
    path("comments/<int:comment_id>/users-who-liked/", vs.users_who_liked_comment, name="comment-users-who-liked"),
    
    # ========== SOCIAL Y COMPARTIR ==========
    path("shared-tasks/", vs.SharedTaskListCreateView.as_view(), name="shared-task-list-create"),
    path("tasks/<int:task_id>/users-who-shared/", vs.users_who_shared_task, name="users-who-shared"),
    path("shared-tasks/<int:shared_task_id>/users-who-liked/", vs.users_who_liked_shared_task, name="shared-task-users-who-liked"),
    path("shared-tasks/comments/<int:comment_id>/users-who-liked/", vs.users_who_liked_shared_comment, name="shared-task-comment-users-who-liked"),
    
    # ========== FAVORITOS (Tareas y Perfiles) ==========
    path("favoritos/agregar/", vs.agregar_favorito, name="agregar-favorito"),
    path("favoritos/listar/", vs.listar_favoritos, name="listar-favoritos"),
    path("favoritos/listar/<uuid:user_id>/", vs.listar_favoritos, name="listar-favoritos-usuario"),
    
    path("pfavoritos/agregar/", vs.agregar_pfavorito, name="agregar-pfavorito"),
    path("pfavoritos/listar/", vs.listar_pfavoritos, name="listar-pfavoritos"),
    path("pfavoritos/listar/<uuid:user_id>/", vs.listar_pfavoritos, name="listar-pfavoritos-usuario"),
    
    # ========== LIKES DE PERFIL ==========
    path("profiles/<uuid:profile_id>/like/", vs.like_unlike_profile, name="like-profile"),
    path("profiles/<uuid:profile_id>/likes/", vs.list_likes, name="profile-likes"),
    
    # ========== CATEGORÍAS ==========
    path("categories/", vs.create_categoryp, name="categories"),
    path("categories/<int:pk>/", vs.create_categoryp, name="delete-category"),
    path("new-categories/", vs.new_category_list_create, name="new-categories"),
    path("new-categories/<int:pk>/", vs.new_category_detail, name="new-category-detail"),
    
    # ========== IMÁGENES Y PORTADAS ==========
    path("imagen-fija/", vs.imagen_fija_list_create, name="imagen-fija"),
    path("portada/", vs.PortadaListCreateView.as_view(), name="portada"),
    path("portada/<int:portada_id>/", vs.portada_update_delete, name="portada-detail"),
    
    # ========== ADMIN PANEL (Dev Legion Control) ==========
    path("verify-admin/", vs.verify_admin, name="verify-admin"),
    path("admin/users/<uuid:user_id>/verify/", vs.admin_verify_user, name="admin-verify"),
        # ========== ADMIN ==========
    path("admin/tasks/<int:task_id>/like/", vs.admin_app_like_task, name="admin-task-like"),
    path("admin/users/<uuid:user_id>/recommend/", vs.admin_recommend_user, name="admin-recommend"),
    path("admin/profiles/<uuid:profile_id>/like/", vs.admin_app_like_profile, name="admin-profile-like"),
    
    # ========== FORO (Forum Posts) ==========
    path("posts/", vs.PostListCreateView.as_view(), name="post-list-create"),
    path("posts/<int:id>/", vs.PostDetailView.as_view(), name="post-detail"),
    path("posts/<int:post_id>/like/", vs.toggle_post_like, name="post-like"),
    
    # ========== TAREAS COMPARTIDAS ==========
    path("shared-tasks/<int:id>/", vs.SharedTaskDetailView.as_view(), name="shared-task-detail"),
    path("shared-tasks/<int:shared_task_id>/like/", vs.toggle_shared_task_like, name="shared-task-like"),
    path("shared-tasks/<int:shared_task_id>/comments/", vs.SharedTaskCommentListCreateView.as_view(), name="shared-task-comments"),
    path("shared-tasks/<int:shared_task_id>/comments/<int:comment_id>/", vs.SharedTaskCommentDetailsView.as_view(), name="shared-task-comment-detail"),
    path("shared-tasks/<int:shared_task_id>/comments/<int:comment_id>/like/", vs.toggle_shared_task_comment_like, name="shared-task-comment-like"),
]