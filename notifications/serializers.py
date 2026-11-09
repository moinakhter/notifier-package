"""Serializers for notification management and ingestion."""
from rest_framework import serializers
from .models import (
    Notification,
    NotificationTemplate,
    RoutingRule,
    SeverityChannelSetting,
    Severity,
    NotificationStatus,
)
from delivery.serializers import DeliveryAttemptSerializer


class NotificationIngestSerializer(serializers.Serializer):
    """Payload serializer for non-blocking notification ingestion."""

    title = serializers.CharField(max_length=500, required=True)
    message = serializers.CharField(required=False, allow_blank=True, default='')
    severity = serializers.ChoiceField(choices=Severity.choices, default=Severity.ERROR)
    project = serializers.CharField(max_length=255, required=False, allow_blank=True)
    project_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    service_name = serializers.CharField(max_length=255, required=False, allow_blank=True, default='')
    server_hostname = serializers.CharField(max_length=255, required=False, allow_blank=True, default='')
    server_ip = serializers.CharField(max_length=50, required=False, allow_blank=True, default='')
    error_type = serializers.CharField(max_length=255, required=False, allow_blank=True, default='')
    traceback = serializers.CharField(required=False, allow_blank=True, default='')
    context = serializers.DictField(required=False, default=dict)
    idempotency_key = serializers.CharField(max_length=255, required=False, allow_blank=True, allow_null=True)
    template_name = serializers.CharField(max_length=255, required=False, allow_blank=True, allow_null=True)


class NotificationListSerializer(serializers.ModelSerializer):
    project_name = serializers.CharField(source='project.name', read_only=True)
    server_name = serializers.CharField(source='server.name', read_only=True)
    server_hostname = serializers.CharField(source='server.hostname', read_only=True)
    delivery_attempts_count = serializers.IntegerField(source='delivery_attempts.count', read_only=True)

    class Meta:
        model = Notification
        fields = [
            'id',
            'project',
            'project_name',
            'server',
            'server_name',
            'server_hostname',
            'title',
            'severity',
            'service_name',
            'error_type',
            'status',
            'occurrence_count',
            'is_acknowledged',
            'is_resolved',
            'delivery_attempts_count',
            'created_at',
            'updated_at',
        ]
        read_only_fields = fields


class NotificationDetailSerializer(serializers.ModelSerializer):
    project_name = serializers.CharField(source='project.name', read_only=True)
    server_name = serializers.CharField(source='server.name', read_only=True)
    server_hostname = serializers.CharField(source='server.hostname', read_only=True)
    acknowledged_by_username = serializers.CharField(source='acknowledged_by.username', read_only=True)
    resolved_by_username = serializers.CharField(source='resolved_by.username', read_only=True)
    delivery_attempts = DeliveryAttemptSerializer(many=True, read_only=True)

    class Meta:
        model = Notification
        fields = [
            'id',
            'project',
            'project_name',
            'server',
            'server_name',
            'server_hostname',
            'title',
            'message',
            'severity',
            'service_name',
            'error_type',
            'traceback',
            'context',
            'status',
            'idempotency_key',
            'content_hash',
            'group_key',
            'occurrence_count',
            'parent_notification',
            'is_acknowledged',
            'acknowledged_by',
            'acknowledged_by_username',
            'acknowledged_at',
            'is_resolved',
            'resolved_by',
            'resolved_by_username',
            'resolved_at',
            'resolution_note',
            'delivery_attempts',
            'created_at',
            'updated_at',
        ]
        read_only_fields = fields


class NotificationAcknowledgeSerializer(serializers.Serializer):
    pass  # No extra fields required, current user is used


class NotificationResolveSerializer(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True, default='')


class NotificationTemplateSerializer(serializers.ModelSerializer):
    project_name = serializers.CharField(source='project.name', read_only=True)

    class Meta:
        model = NotificationTemplate
        fields = [
            'id',
            'project',
            'project_name',
            'name',
            'severity',
            'title_template',
            'message_template',
            'is_active',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class RoutingRuleSerializer(serializers.ModelSerializer):
    project_name = serializers.CharField(source='project.name', read_only=True)
    enabled_channels = serializers.ListField(source='get_channels', read_only=True)

    class Meta:
        model = RoutingRule
        fields = [
            'id',
            'project',
            'project_name',
            'name',
            'description',
            'severity',
            'service_name_pattern',
            'title_pattern',
            'email_enabled',
            'telegram_enabled',
            'whatsapp_enabled',
            'instagram_enabled',
            'enabled_channels',
            'priority',
            'is_active',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class SeverityChannelSettingSerializer(serializers.ModelSerializer):
    project_name = serializers.CharField(source='project.name', read_only=True)
    enabled_channels = serializers.ListField(source='get_channels', read_only=True)

    class Meta:
        model = SeverityChannelSetting
        fields = [
            'id',
            'project',
            'project_name',
            'severity',
            'email_enabled',
            'telegram_enabled',
            'whatsapp_enabled',
            'instagram_enabled',
            'enabled_channels',
        ]
        read_only_fields = ['id']
