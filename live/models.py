"""Models of the live package: the UUIDv7 base and the outbox of events."""

import uuid

from django.core.serializers.json import DjangoJSONEncoder
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from live.operations import NAME_RE


class UUIDModel(models.Model):
    """Base of every model of our own: a UUIDv7 key, time-ordered and generated in Python."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)

    class Meta:
        abstract = True


class OutboxEvent(UUIDModel):
    """A fact recorded by a command in its own transaction (``<app>.<entity>.<fact>``).

    The row commits or rolls back with the command; the live notification goes out after the
    COMMIT. ``delivered_at`` is for the relay of phase 2.
    """

    scope_kind = models.CharField(max_length=32)
    scope_key = models.CharField(max_length=64)
    name = models.CharField(
        max_length=96,
        validators=[RegexValidator(NAME_RE, "Event names must be <app>.<entity>.<fact> (lowercase snake_case).")],
    )
    payload = models.JSONField(default=dict, blank=True, encoder=DjangoJSONEncoder)
    actor = models.CharField(max_length=128, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["scope_kind", "scope_key", "created_at"])]
        ordering = ["created_at", "id"]
        # «Bandeja de salida» is Spanish for an outbox (mail clients say so).
        verbose_name = _("outbox event")
        verbose_name_plural = _("outbox events")

    def __str__(self) -> str:
        return f"{self.name} ({self.scope_kind}:{self.scope_key})"
