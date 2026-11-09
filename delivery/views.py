"""Views for delivery attempts and Dead Letter Queue."""
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter

from .models import DeliveryAttempt, DeadLetterEntry
from .serializers import DeliveryAttemptSerializer, DeadLetterEntrySerializer
from .tasks import reprocess_dead_letter_task


class DeliveryAttemptViewSet(viewsets.ReadOnlyModelViewSet):
    """View delivery history and attempt logs across channels."""

    serializer_class = DeliveryAttemptSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['notification', 'channel', 'status', 'attempt_number']
    search_fields = ['recipient', 'error_message', 'notification__title']
    ordering_fields = ['created_at', 'sent_at']

    def get_queryset(self):
        user = self.request.user
        qs = DeliveryAttempt.objects.select_related('notification', 'notification__project')
        if user.is_staff or user.is_superuser:
            return qs
        return qs.filter(notification__project__owner=user)


class DeadLetterEntryViewSet(viewsets.ModelViewSet):
    """Inspect and reprocess dead-letter queue entries."""

    serializer_class = DeadLetterEntrySerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['channel', 'is_reprocessed']
    search_fields = ['recipient', 'last_error', 'notification__title']
    ordering_fields = ['created_at', 'total_attempts']

    def get_queryset(self):
        user = self.request.user
        qs = DeadLetterEntry.objects.select_related('notification', 'notification__project')
        if user.is_staff or user.is_superuser:
            return qs
        return qs.filter(notification__project__owner=user)

    @action(detail=True, methods=['post'])
    def reprocess(self, request, pk=None):
        """Trigger re-delivery of a failed Dead Letter Queue item."""
        dlq_entry = self.get_object()
        if dlq_entry.is_reprocessed:
            return Response(
                {'status': 'warning', 'message': 'Entry has already been reprocessed.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        res = reprocess_dead_letter_task(str(dlq_entry.id))
        return Response({
            'status': 'success',
            'message': 'Dead Letter Entry re-queued for delivery.',
            'task_result': res,
        }, status=status.HTTP_200_OK)
