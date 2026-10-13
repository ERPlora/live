# erplora-live

Paquete Python compartido por `hub-next` y `saas-next` (fase 1, ronda 11). Reúne lo que las dos
plataformas hacen igual: operaciones declaradas con `@operation` (lecturas en `queries.py`,
escrituras en `services.py`), rutas django-ninja ligadas a esas operaciones, outbox y aviso tras el
COMMIT (`LISTEN/NOTIFY`), consultas vivas por SSE (`/api/live`), servido de la SPA con el
manifiesto de Vite y CSP con nonce. El diseño está en
`../../docs/plans/vamos-a-centrarnos-en-cryptic-abelson.md` (§4.1 y §4.2).

Es un repo propio (`ERPlora/live`, distribución `erplora-live`) con su `uv.lock`; el paquete importable
se llama `live`.
Lo usan los dos proyectos por igual: `hub-next` enchufa su ámbito (fase 1: el primer rótulo del Host;
fase 2: `use_hub`) y `saas-next` el suyo (el usuario); el resto (`live.spa`, `live.csp`, los checks y el
`runserver`) es común. Nace como repo git propio (PLAN §16.4); el monorepo va a una issue.

## Contrato (resumen; detalle en el plan §4.1 y en PLAN §16.2)

- **Operaciones**: `@operation("<app>.<entidad>.<acción>", kind="query"|"command", permission, input,
  output, expose_api=False, ai=None)`; `query` solo en `queries.py` (transacción `READ ONLY`,
  `statement_timeout` 5 s), `command` solo en `services.py`. Cada ruta ninja llama a `run_operation`
  con `operation_id` = nombre de la operación; OpenAPI en `/api/openapi.json` y Swagger en `/api/docs`.
  Errores: `{"error": {"code", "message", "fields"?}}`; 422 `invalid_payload` con `fields`. El 404 de
  una ruta inexistente y el 405 de método equivocado (no llegan a ninguna ruta) los convierte al mismo
  sobre `live.api_errors.ApiErrorEnvelopeMiddleware` (en `MIDDLEWARE` tras auth), bajo
  `LIVE["api_prefix"]` (`/api/` por defecto); no toca JSON, streams, `/api/live` ni `/api/docs`. Los
  mensajes salen en el idioma de la petición (HTTP) o del stream (`ctx.language`, en `/api/live`).
- **Eventos**: `record_event(ctx, "<app>.<entidad>.<hecho>", payload)` solo dentro de un command, en su
  transacción (`live_outboxevent`); tras el COMMIT, `pg_notify(<canal del ámbito>, {"events": […]})` en
  la BD de control. `live.py` de cada app: `live("<consulta>", on=[eventos])`.
- **`/api/live`** (SSE, una conexión por pestaña): `GET /api/live?s=<base64url JSON [{id, op, params}]>`
  con las suscripciones declaradas al abrir; si cambian, el SDK cierra y reabre (debounce 150 ms). Sin
  POST de suscripciones ni afinidad del ALB. Frames `hello`, `result {id, data, rev}`, `error {id,
  error}`, `heartbeat` (15 s) y `bye`; `retry: 3000`; sin `Last-Event-ID` (resultados completos al
  reconectar). Límites: 50 suscripciones, 256 KB por resultado, listas con `limit` ≤ 100. Ejecutor:
  3 hilos por proceso, 1 por ámbito, ráfagas de 150 ms, re-ejecución como ese usuario con los permisos
  releídos y envío solo si cambia el hash; red de seguridad cada 300 s y `resync` al reconectar el
  `LISTEN` (uno por proceso, fuera de PgBouncer). Sin Redis ni Channels.
- **SPA y CSP**: `live.spa` lee el manifiesto de Vite (sin django-vite) y emite `<script type=module>` y
  `modulepreload` con nonce; en DEBUG apunta al servidor de Vite. `live.csp`: nonce + `strict-dynamic` +
  Trusted Types + `connect-src 'self' ipc: http://ipc.localhost`; DEBUG añade el origen de Vite solo a
  connect/style/font/img. `manage.py runserver` (hereda del de daphne) lanza Vite con HMR (`--novite`
  lo omite); `export_spa_catalog` exporta los `.po` (`djangojs`) a JSON.
- **ASGI**: `live.asgi.ignore_root_path(app)` envuelve el `application` de los dos `config/asgi.py`. Daphne
  copia en `scope["root_path"]` la cabecera `Daphne-Root-Path` del cliente y Django la toma como prefijo de
  script; el envoltorio la vacía en `http` y `websocket` (`lifespan` pasa tal cual). ERPlora/hub#2, saas#2.

## Apps y metadatos (ronda 15, PLAN §20)

Toda app nuestra, de `hub-next` y de `saas-next`, hereda `live.meta.LiveAppConfig` y declara ahí sus
metadatos; `live`, `ninja`, `allauth` y `django.contrib.*` no lo son. Detalle en
`../../docs/superpowers/specs/2026-10-13-app-catalog-and-metadata-design.md`.

- **`kind`**: `"platform"` (por defecto; siempre activa: `base`, `control`, `accounts`…) o `"app"`
  (un módulo de `hub-next/apps/<id>/`, que un hub enciende y apaga). La carpeta = `label` = prefijo
  de las operaciones = id en `modules[]` de la foto del SaaS = `slug` de su `Module`; el código nunca
  mira la ruta del paquete.
- **Toda app**: `permissions` (`<app>.<acción>`) y `role_permissions` (`{"hub_manager":
  ["demo.*"]}`); `permissions_for_role` los une sobre todas las apps y expande `<app>.*`.
- **Solo un módulo** (`kind = "app"`): `icon` (Iconify con prefijo de juego, `ion:people`),
  `category` (`live.meta.Category`: `sales`, `catalog`, `people`, `restaurant` u `organization`, con
  etiqueta `en` + `es`; agrupa la página de apps del Hub), `premium` (`False` por defecto; `True` =
  necesita su derecho en la foto del SaaS), `requires` (etiquetas de otros módulos, grafo acíclico)
  y `navigation` (`Nav(id, label, icon, path)`, las entradas del menú). El nombre es el
  `verbose_name`; sin descripción ni versión.
- **Lectura**: `all_live_app_configs()` devuelve todas las apps nuestras instaladas (permisos,
  routers); `module_configs()`, solo las de `kind = "app"` (menú, página de apps, foto del SaaS).
- **Checks** (`live.checks`, etiqueta `live`, registrados al arrancar la app `live`; corren con
  `manage.py check` y `runserver` y miran siempre todas las apps nuestras):
  - `live.E001`: `kind` no es `"platform"` ni `"app"`;
  - `live.E002`: un módulo sin `icon`;
  - `live.E003`: un módulo cuya `category` no es un `Category`;
  - `live.E004`: `requires` nombra algo que no es un módulo (una app de plataforma como `base`, o una
    etiqueta que no existe);
  - `live.E005`: un ciclo en `requires` (un error por ciclo);
  - `live.E006`: una app de plataforma declara `requires`, `category`, `premium` o `navigation`.

  La app de pruebas (`tests/testapp`) es un módulo (`kind = "app"`) con `icon` y `category`, para
  pasarlos.
- **Routers**: `live.ninja.mount_app_routers(api)` monta en la raíz de la API el `router` del `api.py`
  de toda app nuestra (de plataforma o módulo), en el orden de `INSTALLED_APPS`, y devuelve sus
  etiquetas; la que no tiene `api.py` se salta y un `api.py` sin un `Router` de ninja en `router` lanza
  `LiveMisuse`. Lo usa `hub-next/config/api.py`; `saas-next` lo adopta en su carril (PLAN §20.7).

## Slugs reservados

`live.slugs` es la **única** regla del slug de un hub (el primer rótulo de `<slug>.erplora.com`) y la
**única** lista de nombres reservados, para `hub-next` y `saas-next` (Ioan, 2026-10-13; PLAN §16.14).

- **Regla**: `HUB_SLUG_RE` (`^[a-z0-9]([a-z0-9-]{1,61}[a-z0-9])?$`): minúsculas, cifras y guiones, sin
  guion al principio ni al final; 3–63 caracteres; nunca empieza por `xn--` (punycode).
- **Reservados** (`RESERVED_HUB_SLUGS`): palabras de sistema. El nuestro es `hubs` (host de
  plataforma: el admin del Hub para el staff, ronda 13, PLAN §18); `hub` sigue reservado y el resto
  son nombres bloqueados para que ningún cliente los tome. Para añadir uno se edita esta lista, no se
  copia en otro sitio.
- **API**: `validate_hub_slug(slug)` devuelve el slug o lanza `ValueError` con el código (`reserved`,
  `invalid_format`, `too_short`, `too_long`, `punycode`); `is_reserved_hub_slug(slug)` (sin distinguir
  mayúsculas); `hub_slug_validator` para `validators=[…]` de un campo de modelo o formulario
  (`ValidationError` con ese código y mensaje en `en` + `es`). No uses `RegexValidator(HUB_SLUG_RE)`:
  su `$` admite un salto de línea final.
- **Mínimo en local**: `LIVE["hub_slug_min_length"]` (3 por defecto). Solo el desarrollo local lo baja
  a 1 (`1 if DEBUG else 3`), porque los hubs de demo son `a` y `b`; producción aplica 3. La expresión
  admite 1 carácter o 3–63, nunca 2.
- TLS: certificado comodín `*.erplora.com`; no hay límite de hubs.

## Cómo se prueba

Los tests van con pytest + pytest-django contra Postgres 17 (nunca SQLite). Se corren **desde la
carpeta del paquete**, con su propio `.venv` y su `uv.lock`; vale igual con el repo suelto
(`ERPlora/live`) que como submódulo de `hub` o `saas`:

```bash
uv sync            # crea el .venv del paquete con sus dependencias y el grupo dev
uv run pytest -q   # crea la BD test_hub y corre la suite
```

Hace falta un Postgres. El de `erplora-next` vale tal cual: desde su raíz, `docker compose up -d
postgres` (jamás `down -v`). Si no, cualquier Postgres 17 apuntado con las variables `DB_NAME`,
`DB_USER`, `DB_PASSWORD`, `DB_HOST` y `DB_PORT` (por defecto `hub`/`hub`/`hub`/`127.0.0.1`/`5432`,
las del `compose.yaml`). Los ajustes de prueba están en `tests/settings.py` y la app mínima de
apoyo en `tests/testapp/`.
