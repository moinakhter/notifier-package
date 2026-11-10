"""Admin configuration for projects app."""
from django.contrib import admin
from .models import Project, APIKey, Server


class APIKeyInline(admin.TabularInline):
    model = APIKey
    extra = 0
    readonly_fields = ('prefix', 'hashed_key', 'created_at', 'last_used_at', 'revoked_at')
    fields = ('name', 'prefix', 'is_active', 'expires_at', 'created_at', 'last_used_at', 'revoked_at')


class ServerInline(admin.TabularInline):
    model = Server
    extra = 0


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'environment', 'log_retention_days', 'notify_exceptions_only', 'owner', 'is_active', 'created_at')
    list_editable = ('log_retention_days', 'notify_exceptions_only', 'is_active')
    list_filter = ('environment', 'is_active', 'notify_exceptions_only')
    search_fields = ('name', 'slug')
    prepopulated_fields = {'slug': ('name',)}
    inlines = [APIKeyInline, ServerInline]


@admin.register(APIKey)
class APIKeyAdmin(admin.ModelAdmin):
    list_display = ('prefix', 'name', 'project', 'is_active', 'created_at', 'last_used_at')
    list_filter = ('is_active',)
    search_fields = ('prefix', 'name', 'project__name')
    readonly_fields = ('prefix', 'hashed_key', 'created_at', 'last_used_at', 'revoked_at')


@admin.register(Server)
class ServerAdmin(admin.ModelAdmin):
    list_display = ('name', 'hostname', 'project', 'environment', 'is_active', 'last_seen_at')
    list_filter = ('environment', 'is_active')
    search_fields = ('name', 'hostname', 'project__name')
