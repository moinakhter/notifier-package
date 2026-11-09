"""Serializers for delivery attempts and Dead Letter Queue."""
from rest_framework import serializers
from .models import DeliveryAttempt, DeadLetterEntry


class DeliveryAttemptSerializer(serializers.ModelSerializer):
    notification_title = serializers.CharField(source='notification.title', read_only=True)
    notification_severity = serializers.CharField(source='notification.severity', read_only=True)

    class Meta:
        model = DeliveryAttempt
        fields = [
            'id',
            'notification',
            'notification_title',
            'notification_severity',
            'channel',
            'recipient',
            'status',
            'attempt_number',
            'response_code',
            'response_body',
            'error_message',
            'sent_at',
            'created_at',
        ]
        read_only_fields = fields


class DeadLetterEntrySerializer(serializers.ModelSerializer):
    notification_title = serializers.CharField(source='notification.title', read_only=True)
    notification_severity = serializers.CharField(source='notification.severity', read_only=True)

    class Meta:
        model = DeadLetterEntry
        fields = [
            'id',
            'notification',
            'notification_title',
            'notification_severity',
            'channel',
            'recipient',
            'last_error',
            'total_attempts',
            'payload',
            'is_reprocessed',
            'reprocessed_at',
            'created_at',
        ]
        read_only_fields = fields
