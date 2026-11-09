"""Admin configuration for notifications app."""
from django.contrib import admin
from .models import (
    Notification,
    NotificationTemplate,
    RoutingRule,
    SeverityChannelSetting,
)


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('title', 'project', 'severity', 'status', 'service_name', 'occurrence_count', 'is_acknowledged', 'is_resolved', 'created_at')
    list_filter = ('severity', 'status', 'is_acknowledged', 'is_resolved', 'project')
    search_fields = ('title', 'message', 'error_type', 'service_name', 'traceback')
    readonly_fields = ('id', 'content_hash', 'group_key', 'created_at', 'updated_at')
    date_hierarchy = 'created_at'


@admin.register(NotificationTemplate)
class NotificationTemplateAdmin(admin.ModelAdmin):
    list_display = ('name', 'project', 'severity', 'is_active', 'created_at')
    list_filter = ('severity', 'is_active', 'project')
    search_fields = ('name', 'title_template', 'message_template')


@admin.register(RoutingRule)
class RoutingRuleAdmin(admin.ModelAdmin):
    list_display = ('name', 'project', 'severity', 'priority', 'email_enabled', 'telegram_enabled', 'whatsapp_enabled', 'instagram_enabled', 'is_active')
    list_filter = ('severity', 'is_active', 'project')
    search_fields = ('name', 'description')


@admin.register(SeverityChannelSetting)
class SeverityChannelSettingAdmin(admin.ModelAdmin):
    list_display = ('project', 'severity', 'email_enabled', 'telegram_enabled', 'whatsapp_enabled', 'instagram_enabled')
    list_filter = ('severity', 'project')
