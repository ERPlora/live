# erplora-live

Paquete Python compartido por `hub-next` y `saas-next` (fase 1, ronda 11). Reúne lo que las dos
plataformas hacen igual: operaciones declaradas con `@operation` (lecturas en `queries.py`,
escrituras en `services.py`), rutas django-ninja ligadas a esas operaciones, outbox y aviso tras el
COMMIT (`LISTEN/NOTIFY`), consultas vivas por SSE (`/api/live`), servido de la SPA con el
manifiesto de Vite y CSP con nonce. El diseño está en
`../../docs/plans/vamos-a-centrarnos-en-cryptic-abelson.md` (§4.1 y §4.2).

Es un miembro del workspace `uv` de la raíz (`erplora-live`); el paquete importable se llama `live`.

## Cómo se prueba

Los tests van con pytest + pytest-django contra Postgres 17 (nunca SQLite). Desde la raíz de
`erplora-next`:

```bash
docker compose up -d postgres     # Postgres local (BD hub y saas); jamás `down -v`
uv sync                           # instala el paquete y el grupo dev en el .venv de la raíz
uv run pytest packages/live -q    # crea la BD test_hub y corre la suite
```

La conexión sale de las variables `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST` y `DB_PORT`
(por defecto `hub`/`hub`/`hub`/`127.0.0.1`/`5432`, las del `compose.yaml`). Los ajustes de prueba
están en `tests/settings.py` y la app mínima de apoyo en `tests/testapp/`.
