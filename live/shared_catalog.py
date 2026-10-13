"""The contract of the `shared` schema of the `saas` database (round 16).

The SaaS owns the tables and their migrations (saas-next/apps); the Hub writes them through a
mirror with managed = False (hub-next/shared). Both name the schema in db_table, already quoted.
"""

from django.db import models

from live.models import UUIDModel

APP_TABLE = '"shared"."app"'
APP_DOC_TABLE = '"shared"."app_doc"'
DOC_LANGUAGES = ("es", "en")


class AbstractApp(models.Model):
    id = models.CharField(primary_key=True, max_length=63)
    name_en = models.CharField(max_length=80)
    name_es = models.CharField(max_length=80)
    summary_en = models.CharField(max_length=120)
    summary_es = models.CharField(max_length=120)
    description_en = models.TextField()
    description_es = models.TextField()
    icon = models.CharField(max_length=100)
    icon_svg = models.TextField()
    # No choices: the SaaS tolerates an unknown one (§5.3).
    category = models.CharField(max_length=20)
    premium = models.BooleanField()
    requires = models.JSONField(default=list)
    verticals = models.JSONField(default=list)
    listed = models.BooleanField()
    hub_version = models.CharField(max_length=64)
    registered_at = models.DateTimeField()

    class Meta:
        abstract = True


class AbstractAppDoc(UUIDModel):
    # A relative name: each project's concrete AppDoc points at its own App.
    app = models.ForeignKey("App", on_delete=models.PROTECT, related_name="docs")
    lang = models.CharField(
        max_length=8, choices=[(code, code) for code in DOC_LANGUAGES]
    )
    markdown = models.TextField()
    source_hash = models.CharField(max_length=64)
    updated_at = models.DateTimeField()

    class Meta:
        abstract = True
