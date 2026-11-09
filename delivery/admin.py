"""Admin configuration for delivery app."""
from django.contrib import admin
from .models import DeliveryAttempt, DeadLetterEntry


@admin.register(DeliveryAttempt)
class DeliveryAttemptAdmin(admin.ModelAdmin):
    list_display = ('notification', 'channel', 'recipient', 'status', 'attempt_number', 'sent_at')
    list_filter = ('channel', 'status')
    search_fields = ('recipient', 'notification__title')
    readonly_fields = ('id', 'created_at')


@admin.register(DeadLetterEntry)
class DeadLetterEntryAdmin(admin.ModelAdmin):
    list_display = ('notification', 'channel', 'recipient', 'total_attempts', 'is_reprocessed', 'created_at')
    list_filter = ('channel', 'is_reprocessed')
    search_fields = ('recipient', 'last_error')
    readonly_fields = ('id', 'created_at')
