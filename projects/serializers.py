"""Serializers for project management."""
from rest_framework import serializers
from .models import Project, APIKey, Server, Environment


class ServerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Server
        fields = [
            'id',
            'project',
            'name',
            'hostname',
            'ip_address',
            'environment',
            'is_active',
            'last_seen_at',
            'metadata',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'last_seen_at', 'created_at', 'updated_at']


class APIKeySerializer(serializers.ModelSerializer):
    is_expired = serializers.BooleanField(read_only=True)

    class Meta:
        model = APIKey
        fields = [
            'id',
            'project',
            'name',
            'prefix',
            'is_active',
            'is_expired',
            'last_used_at',
            'expires_at',
            'created_at',
            'revoked_at',
        ]
        read_only_fields = ['id', 'prefix', 'last_used_at', 'created_at', 'revoked_at']


class APIKeyCreateSerializer(serializers.ModelSerializer):
    raw_key = serializers.CharField(read_only=True)

    class Meta:
        model = APIKey
        fields = [
            'id',
            'project',
            'name',
            'prefix',
            'expires_at',
            'raw_key',
            'created_at',
        ]
        read_only_fields = ['id', 'prefix', 'created_at', 'raw_key']

    def create(self, validated_data):
        prefix, full_key, hashed = APIKey.generate_raw_key()
        api_key = APIKey.objects.create(
            project=validated_data['project'],
            name=validated_data['name'],
            prefix=prefix,
            hashed_key=hashed,
            expires_at=validated_data.get('expires_at'),
        )
        api_key.raw_key = full_key
        return api_key


class APIKeyRotateSerializer(serializers.Serializer):
    new_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    raw_key = serializers.CharField(read_only=True)
    new_key_id = serializers.UUIDField(read_only=True)


class ProjectSerializer(serializers.ModelSerializer):
    server_count = serializers.IntegerField(source='servers.count', read_only=True)
    api_key_count = serializers.IntegerField(source='api_keys.count', read_only=True)
    servers = ServerSerializer(many=True, read_only=True)

    class Meta:
        model = Project
        fields = [
            'id',
            'name',
            'slug',
            'description',
            'owner',
            'environment',
            'is_active',
            'rate_limit',
            'server_count',
            'api_key_count',
            'servers',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'slug', 'owner', 'created_at', 'updated_at']

    def create(self, validated_data):
        request = self.context.get('request')
        if request and hasattr(request, 'user') and request.user.is_authenticated:
            validated_data['owner'] = request.user
        return super().create(validated_data)
