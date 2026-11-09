"""Serializers for notification channel configurations."""
from rest_framework import serializers
from .models import (
    EmailConfiguration,
    TelegramConfiguration,
    WhatsAppConfiguration,
    InstagramConfiguration,
)


def mask_secret(value: str) -> str:
    if not value or len(value) < 6:
        return '******'
    return f'{value[:3]}...{value[-3:]}'


class EmailConfigurationSerializer(serializers.ModelSerializer):
    smtp_password = serializers.CharField(write_only=True, required=False)
    masked_password = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = EmailConfiguration
        fields = [
            'id',
            'project',
            'name',
            'smtp_host',
            'smtp_port',
            'smtp_username',
            'smtp_password',
            'masked_password',
            'use_tls',
            'use_ssl',
            'from_email',
            'from_name',
            'recipients',
            'is_active',
            'is_verified',
            'last_tested_at',
            'last_test_result',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'is_verified', 'last_tested_at', 'last_test_result', 'created_at', 'updated_at']

    def get_masked_password(self, obj):
        return mask_secret(obj.smtp_password)


class TelegramConfigurationSerializer(serializers.ModelSerializer):
    bot_token = serializers.CharField(write_only=True, required=False)
    masked_token = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = TelegramConfiguration
        fields = [
            'id',
            'project',
            'name',
            'bot_token',
            'masked_token',
            'chat_ids',
            'parse_mode',
            'is_active',
            'is_verified',
            'last_tested_at',
            'last_test_result',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'is_verified', 'last_tested_at', 'last_test_result', 'created_at', 'updated_at']

    def get_masked_token(self, obj):
        return mask_secret(obj.bot_token)


class WhatsAppConfigurationSerializer(serializers.ModelSerializer):
    access_token = serializers.CharField(write_only=True, required=False)
    masked_token = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = WhatsAppConfiguration
        fields = [
            'id',
            'project',
            'name',
            'phone_number_id',
            'access_token',
            'masked_token',
            'business_account_id',
            'api_version',
            'recipient_numbers',
            'is_active',
            'is_verified',
            'last_tested_at',
            'last_test_result',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'is_verified', 'last_tested_at', 'last_test_result', 'created_at', 'updated_at']

    def get_masked_token(self, obj):
        return mask_secret(obj.access_token)


class InstagramConfigurationSerializer(serializers.ModelSerializer):
    access_token = serializers.CharField(write_only=True, required=False)
    masked_token = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = InstagramConfiguration
        fields = [
            'id',
            'project',
            'name',
            'page_id',
            'access_token',
            'masked_token',
            'instagram_account_id',
            'api_version',
            'recipient_ids',
            'is_active',
            'is_verified',
            'last_tested_at',
            'last_test_result',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'is_verified', 'last_tested_at', 'last_test_result', 'created_at', 'updated_at']

    def get_masked_token(self, obj):
        return mask_secret(obj.access_token)
