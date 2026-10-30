from urllib.parse import quote

from django.conf import settings

from storages.backends.s3boto3 import S3Boto3Storage
from storages.utils import clean_name


class SupabaseStorage(S3Boto3Storage):
    default_acl = None
    file_overwrite = False
    querystring_auth = False

    def url(self, name, parameters=None, expire=None, http_method=None):
        base_url = settings.SUPABASE_STORAGE_PUBLIC_URL.rstrip("/")
        normalized_name = self._normalize_name(clean_name(name))
        return f"{base_url}/{quote(normalized_name, safe='/')}"


if getattr(settings, 'USE_S3', False):
    from storages.backends.s3boto3 import S3Boto3Storage

    class SignatureStorage(S3Boto3Storage):
        location = 'signatures'
        default_acl = 'public-read'
        file_overwrite = True

    class ThumbnailStorage(S3Boto3Storage):
        location = 'BlogThumbnails'
        default_acl = 'public-read'
        file_overwrite = True

    class BusinessPagePhotoStorage(S3Boto3Storage):
        location = "BusinessPagePhotos"
        default_acl = 'public-read'
        file_overwrite = False

    class ListingImageStorage(S3Boto3Storage):
        location = "ListingImages"
        default_acl = 'public-read'
        file_overwrite = False

    class ProfileImageStorage(S3Boto3Storage):
        location = "ProfileImages"
        default_acl = 'public-read'
        file_overwrite = False

    class ImagenText(S3Boto3Storage):
        location = 'ImagenText'
        default_acl = 'public-read'
        file_overwrite = True

    class VideoStorage(S3Boto3Storage):
        location = 'videos'
        default_acl = 'public-read'
        file_overwrite = False

    class ArchivosText(S3Boto3Storage):
        location = 'todo'
        default_acl = 'public-read'
        file_overwrite = False

else:
    from django.core.files.storage import FileSystemStorage

    class SignatureStorage(FileSystemStorage): pass
    class ThumbnailStorage(FileSystemStorage): pass
    class BusinessPagePhotoStorage(FileSystemStorage): pass
    class ListingImageStorage(FileSystemStorage): pass
    class ProfileImageStorage(FileSystemStorage): pass
    class ImagenText(FileSystemStorage): pass
    class VideoStorage(FileSystemStorage): pass
    class ArchivosText(FileSystemStorage): pass
    class DynamicImageStorage(FileSystemStorage): pass
# from storages.backends.s3boto3 import S3Boto3Storage
# from django.conf import settings

# class SignatureStorage(S3Boto3Storage):
#     location = 'signatures'
#     default_acl = 'public-read'
#     file_overwrite = True

# class ThumbnailStorage(S3Boto3Storage):
#     location = 'BlogThumbnails'
#     default_acl = 'public-read'
#     file_overwrite = True

# class BusinessPagePhotoStorage(S3Boto3Storage):
#     location = "BusinessPagePhotos"
#     default_acl = 'public-read'
#     file_overwrite = False

# class ListingImageStorage(S3Boto3Storage):
#     location = "ListingImages"
#     default_acl = 'public-read'
#     file_overwrite = False

# class ProfileImageStorage(S3Boto3Storage):
#     location = "ProfileImages"
#     default_acl = 'public-read'
#     file_overwrite = False

# class ImagenText(S3Boto3Storage):
#     location = 'ImagenText'
#     default_acl = 'public-read'
#     file_overwrite = True

# class VideoStorage(S3Boto3Storage):
#     location = 'videos'  # Esta es la carpeta en S3 donde se guardarán los videos
#     default_acl = 'public-read'  # Esto asegura que los videos sean públicamente accesibles
#     file_overwrite = False  # Cambia a True si quieres que los nuevos archivos sobrescriban los antiguos con el mismo nombre

# class ArchivosText(S3Boto3Storage):
#     location = 'todo'  # Esta es la carpeta en S3 donde se guardarán los videos
#     default_acl = 'public-read'  # Esto asegura que los videos sean públicamente accesibles
#     file_overwrite = False  # Cambia a True si quieres que los nuevos archivos sobrescriban los antiguos con el mismo nombre