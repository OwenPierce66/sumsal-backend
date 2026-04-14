from django.urls import path
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)

from . import views as vs
from .throttling import LoginThrottle, RefreshThrottle

urlpatterns = [
    # ========== AUTENTICACIÓN ==========
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
    
    # ========== USUARIOS ==========
    path("users/", vs.list_users, name="list-users"),
    path("users/<int:user_id>/portadas/", vs.obtener_portadas_usuario, name="user-portadas"),
    path("users/<int:user_id>/imagen-fija/", vs.obtener_imagen_fija_usuario, name="user-imagen-fija"),
    path("user-details/", vs.get_user_details, name="user-details"),
    path("profile/", vs.get_current_user_profile, name="user-profile"),
    
    # ========== TAREAS ==========
    path("tasks/", vs.TaskListCreateView.as_view(), name="task-list-create"),
    path("tasks/<int:id>/", vs.TaskDetailView.as_view(), name="task-detail"),
    path("tasks/<int:task_id>/like/", vs.toggle_task_like, name="task-like"),
    path("tasks/<int:task_id>/users-who-liked/", vs.users_who_liked_task, name="users-who-liked"),
    
    # ========== COMPARTIR TAREAS ==========
    path("shared-tasks/", vs.create_shared_task, name="create-shared-task"),
    path("shared-tasks/<int:shared_task_id>/", vs.delete_shared_task, name="delete-shared-task"),
    path("tasks/<int:task_id>/users-who-shared/", vs.users_who_shared_task, name="users-who-shared"),
    
    # ========== COMENTARIOS EN TAREAS ==========
    path("tasks/<int:task_id>/comments/", vs.TaskCommentListCreateView.as_view(), name="task-comments"),
    path("comments/<int:comment_id>/like/", vs.toggle_comment_like, name="comment-like"),
    path("comments/<int:comment_id>/users-who-liked/", vs.users_who_liked_task, name="users-who-liked-comment"),
    
    # ========== FAVORITOS DE TAREAS ==========
    path("favoritos/agregar/", vs.agregar_favorito, name="agregar-favorito"),
    path("favoritos/<int:task_id>/eliminar/", vs.agregar_favorito, name="eliminar-favorito"),
    path("favoritos/listar/", vs.listar_favoritos, name="listar-favoritos"),
    path("favoritos/listar/<int:user_id>/", vs.listar_favoritos, name="listar-favoritos-usuario"),
    
    # ========== FAVORITOS DE PERFILES ==========
    path("pfavoritos/agregar/", vs.agregar_pfavorito, name="agregar-pfavorito"),
    path("pfavoritos/listar/", vs.listar_pfavoritos, name="listar-pfavoritos"),
    path("pfavoritos/listar/<int:user_id>/", vs.listar_pfavoritos, name="listar-pfavoritos-usuario"),
    
    # ========== LIKES EN PERFILES ==========
    path("profiles/<int:profile_id>/like/", vs.like_unlike_profile, name="like-profile"),
    path("profiles/<int:profile_id>/likes/", vs.list_likes, name="profile-likes"),
    
    # ========== CATEGORÍAS ==========
    path("categories/", vs.create_categoryp, name="categories"),
    path("categories/<int:pk>/", vs.create_categoryp, name="delete-category"),
    path("new-categories/", vs.new_category_list_create, name="new-categories"),
    path("new-categories/<int:pk>/", vs.new_category_detail, name="new-category-detail"),
    
    # ========== IMÁGENES ==========
    path("imagen-fija/", vs.imagen_fija_list_create, name="imagen-fija"),
    
    # ========== PORTADAS ==========
    path("portada/", vs.portada_list_create, name="portada"),
    path("portada/<int:portada_id>/", vs.portada_update_delete, name="portada-detail"),
    
    # ========== ADMIN ==========
    path("verify-admin/", vs.verify_admin, name="verify-admin"),
    path("admin/users/<int:user_id>/verify/", vs.admin_verify_user, name="admin-verify"),
    path("admin/users/<int:user_id>/recommend/", vs.admin_recommend_user, name="admin-recommend"),
    path("admin/tasks/<int:task_id>/like/", vs.admin_app_like_task, name="admin-task-like"),
    path("admin/profiles/<int:profile_id>/like/", vs.admin_app_like_profile, name="admin-profile-like"),
]
