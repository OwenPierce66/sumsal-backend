from rest_framework.throttling import UserRateThrottle, AnonRateThrottle

class UserMeThrottle(UserRateThrottle):
    scope = 'user_me'

class RegisterAnonThrottle(AnonRateThrottle):
    scope = 'auth'

class RegisterUserThrottle(UserRateThrottle):
    scope = 'auth'

class LoginThrottle(UserRateThrottle):
    scope = 'auth'

class RefreshThrottle(UserRateThrottle):
    scope = 'auth'

class BurstThrottle(UserRateThrottle):
    scope = 'burst'

class SustainedThrottle(UserRateThrottle):
    scope = 'sustained'

class VaultThrottle(UserRateThrottle):
    scope = 'vault'

class UploadThrottle(UserRateThrottle):
    scope = 'uploads'

class PublicApiThrottle(AnonRateThrottle):
    scope = 'public'