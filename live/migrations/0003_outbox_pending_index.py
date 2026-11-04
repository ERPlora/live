"""``live`` takes over the outbox's partial index of pending events (hub#704).

The Hub's ``base/0006`` made it, by hand, on every database deployed so far: there this migration finds it, leaves it as
it is and only writes it down in the state. A database without one gets it here. It looks in the catalog first, because
``CREATE INDEX … IF NOT EXISTS`` takes its SHARE lock and asks to own the table before it looks, and every deployed
database goes through this in a deploy, with its outbox in use.
"""

from django.db import migrations, models

NAME = "base_outbox_pending"
CREATE_IF_MISSING = f"""
DO $$
BEGIN
    IF to_regclass('{NAME}') IS NULL THEN
        CREATE INDEX {NAME} ON live_outboxevent (created_at, id) WHERE delivered_at IS NULL;
    END IF;
END
$$
"""


class Migration(migrations.Migration):

    dependencies = [
        ('live', '0002_outboxevent_verbose_names'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunSQL(CREATE_IF_MISSING, f"DROP INDEX IF EXISTS {NAME}")],
            state_operations=[
                migrations.AddIndex(
                    model_name='outboxevent',
                    index=models.Index(condition=models.Q(('delivered_at__isnull', True)), fields=['created_at', 'id'], name=NAME),
                ),
            ],
        ),
    ]
