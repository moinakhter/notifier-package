"""API Key authentication for Django REST Framework."""
import hmac
from django.utils import timezone
from rest_framework import authentication, exceptions

from .models import APIKey


class APIKeyAuthentication(authentication.BaseAuthentication):
    """
    Authenticate requests using an API Key.
    Supports:
      - X-API-Key: <key>
      - Authorization: Bearer <key>
      - Authorization: ApiKey <key>
    """

    def authenticate(self, request):
        raw_key = None

        # Check X-API-Key header
        if 'HTTP_X_API_KEY' in request.META:
            raw_key = request.META['HTTP_X_API_KEY'].strip()
        elif 'HTTP_AUTHORIZATION' in request.META:
            auth_header = request.META['HTTP_AUTHORIZATION'].strip().split()
            if len(auth_header) == 2 and auth_header[0].lower() in ('bearer', 'apikey'):
                raw_key = auth_header[1]

        if not raw_key:
            return None

        # Extract prefix if format matches ntf_xxxxxxxx_...
        hashed = APIKey.hash_key(raw_key)

        try:
            # Query active keys
            keys = APIKey.objects.select_related('project', 'project__owner').filter(is_active=True)
            matched_key = None
            for key in keys:
                if hmac.compare_digest(key.hashed_key, hashed):
                    matched_key = key
                    break

            if not matched_key:
                raise exceptions.AuthenticationFailed('Invalid API key.')

            if matched_key.is_expired:
                raise exceptions.AuthenticationFailed('API key has expired.')

            if not matched_key.project.is_active:
                raise exceptions.AuthenticationFailed('Project is inactive or suspended.')

            # Update last used timestamp
            APIKey.objects.filter(pk=matched_key.pk).update(last_used_at=timezone.now())

            # Attach project & key directly to request
            request.project = matched_key.project
            request.api_key = matched_key

            return (matched_key.project.owner, matched_key)

        except APIKey.DoesNotExist:
            raise exceptions.AuthenticationFailed('Invalid API key.')

    def authenticate_header(self, request):
        return 'X-API-Key'
