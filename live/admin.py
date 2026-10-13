"""Django admin of the live package: the outbox, read-only (only commands write events)."""

from django.contrib import admin

from live.models import OutboxEvent


@admin.register(OutboxEvent)
class OutboxEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "name", "scope_kind", "scope_key", "actor", "delivered_at")
    list_filter = ("scope_kind",)
    search_fields = ("name", "scope_key", "actor")
    date_hierarchy = "created_at"

    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
