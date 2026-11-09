"""Admin configuration for channels_config app."""
from django.contrib import admin
from .models import (
    EmailConfiguration,
    TelegramConfiguration,
    WhatsAppConfiguration,
    InstagramConfiguration,
)


@admin.register(EmailConfiguration)
class EmailConfigurationAdmin(admin.ModelAdmin):
    list_display = ('name', 'project', 'from_email', 'smtp_host', 'is_active', 'is_verified', 'last_tested_at')
    list_filter = ('is_active', 'is_verified')
    search_fields = ('name', 'from_email', 'project__name')


@admin.register(TelegramConfiguration)
class TelegramConfigurationAdmin(admin.ModelAdmin):
    list_display = ('name', 'project', 'parse_mode', 'is_active', 'is_verified', 'last_tested_at')
    list_filter = ('is_active', 'is_verified')
    search_fields = ('name', 'project__name')


@admin.register(WhatsAppConfiguration)
class WhatsAppConfigurationAdmin(admin.ModelAdmin):
    list_display = ('name', 'project', 'phone_number_id', 'is_active', 'is_verified', 'last_tested_at')
    list_filter = ('is_active', 'is_verified')
    search_fields = ('name', 'project__name')


@admin.register(InstagramConfiguration)
class InstagramConfigurationAdmin(admin.ModelAdmin):
    list_display = ('name', 'project', 'instagram_account_id', 'is_active', 'is_verified', 'last_tested_at')
    list_filter = ('is_active', 'is_verified')
    search_fields = ('name', 'project__name')
