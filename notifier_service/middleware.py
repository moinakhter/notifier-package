"""
Django middleware for capturing unhandled view exceptions
and streaming them to the central Notifier Service.
"""
from django.conf import settings
from .client import NotifierClient


class NotifierExceptionMiddleware:
    """
    Middleware that captures uncaught exceptions in Django views
    and sends them to the central Notifier Service without blocking the request.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        endpoint = getattr(settings, 'NOTIFIER_SERVICE_URL', 'http://127.0.0.1:8000')
        project = getattr(settings, 'NOTIFIER_PROJECT_NAME', 'django-app')
        api_key = getattr(settings, 'NOTIFIER_API_KEY', None)
        self.client = NotifierClient(
            endpoint=endpoint,
            project=project,
            api_key=api_key,
            async_send=True,
        )

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        context = {
            'path': request.path,
            'method': request.method,
            'user': str(getattr(request, 'user', 'anonymous')),
            'query_params': dict(request.GET.items()),
        }
        self.client.capture_exception(
            exc=exception,
            title=f'500 Error: {request.method} {request.path}',
            severity='CRITICAL',
            service_name=getattr(settings, 'NOTIFIER_SERVICE_NAME', 'web'),
            context=context,
        )
        return None
