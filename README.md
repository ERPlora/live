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
  la BD de control. `live.py` de cada app: `live("<consulta>", on=[eventos])`. En el admin de Django
  (`live.admin`, solo lectura) la sección se llama «Live»/«Tiempo real» y el modelo «outbox events»/«eventos de
  la bandeja de salida», traducidos por `live/locale/es` (`tests/test_admin.py`).
- **`/api/live`** (SSE, una conexión por pestaña): `GET /api/live?s=<base64url JSON [{id, op, params}]>`
  con las suscripciones declaradas al abrir; si cambian, el SDK cierra y reabre (debounce 150 ms). Sin
  POST de suscripciones ni afinidad del ALB. Frames `hello`, `result {id, data, rev}`, `error {id,
  error}`, `heartbeat` (15 s) y `bye`; `retry: 3000`; sin `Last-Event-ID` (resultados completos al
  reconectar). Límites: 50 suscripciones, 256 KB por resultado, listas con `limit` ≤ 100. Ejecutor:
  3 hilos por proceso, 1 por ámbito, ráfagas de 150 ms, re-ejecución como ese usuario con los permisos
  releídos y envío solo si cambia el hash; red de seguridad cada 300 s y `resync` al reconectar el
  `LISTEN` (uno por proceso, fuera de PgBouncer). Sin Redis ni Channels.
- **SPA y CSP**: `live.spa` lee el manifiesto de Vite (sin django-vite) y emite `<script type=module>` y
  `modulepreload` con nonce; en DEBUG apunta al servidor de Vite. `spa_assets(request, entry=…)` da
  otra entrada del mismo build (p. ej. `frontend/public.ts`, la web pública de `saas-next`, ronda 16);
  sin `entry`, la de `LIVE["spa"]["entry"]`. `live.csp`: nonce + `strict-dynamic` +
  Trusted Types + `connect-src 'self' ipc: http://ipc.localhost`; DEBUG añade el origen de Vite solo a
  connect/style/font/img. `manage.py runserver` (hereda del de daphne) lanza Vite con HMR (`--novite`
  lo omite); `export_spa_catalog` exporta los `.po` (`djangojs`) a JSON.
- **ASGI**: `live.asgi.ignore_root_path(app)` envuelve el `application` de los dos `config/asgi.py`. Daphne
  copia en `scope["root_path"]` la cabecera `Daphne-Root-Path` del cliente y Django la toma como prefijo de
  script; el envoltorio la vacía en `http` y `websocket` (`lifespan` pasa tal cual). ERPlora/hub#2, saas#2.

## Apps y metadatos (rondas 15 y 16, PLAN §20 y §21)

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
  `verbose_name`; sin versión. La página de apps del Hub pinta solo icono y nombre.
- **Solo un módulo, para la tienda pública** (ronda 16; `register_apps` los escribe en `shared.app`):
  `summary` (una línea, ≤ 120 caracteres, `gettext_lazy`), `description` (un párrafo),
  `verticals` (ids de vertical; de ellos se derivan las plantillas por vertical) y `listed` (`True`
  por defecto; `False` lo saca de la tienda, como `apps/demo`).
- **Solo un módulo, para el Inicio del Hub** (ronda PLAN-HUB 2026-10-21, los «hooks» del manifiesto
  viejo sin manifiesto; los agrega `base` con `base.setup.status`, `base.widget.list` y
  `base.bell.counters`): tres listas de dataclasses congeladas, como `Nav`, vacías por defecto.
  - `setup: list[SetupStep]`, los pasos de «Termina de configurar tu negocio»: `key`, `operation`
    (una consulta de su propio `queries.py`), `title` y `route`, obligatorios; `description`, `icon`,
    `params`, `configured_when` (lista de `SetupCheck(field, truthy=… | equals=…)` sobre la primera
    fila del resultado; vacía = basta con que haya fila), `permission` (la que hace falta para
    configurarlo), `countries` (ISO 3166-1 alfa-2; vacío = todos), `order`, `required` (`True` por
    defecto = funcional; `False` = recomendado; el nivel legal lo da `base`) y `refresh_on`.
  - `widgets: list[Widget]`, los paneles del tablero: `key` y `title`; `icon`, `category`, `size`
    (`WIDGET_SIZES`: `sm`, `md` por defecto, `lg`), `permission`, `verticals` (vacío = todas),
    `default`, `refresh_on` y, o bien `kind` (`WIDGET_KINDS`: `kpi`, `stat`, `sparkline`,
    `bar-list`, `timeline`, `chart`) con `operation`, `params`, `map` (prop → campo) y `options`, o
    bien `component` (un componente Vue de `frontend/components/` del módulo, sin `.vue`).
  - `bell: list[BellCounter]`, los contadores de la campana: `key`, `operation` (su primera fila
    trae `count`), `route` y `label`; `icon`, `params`, `permission` y `refresh_on`.
- **Lectura**: `all_live_app_configs()` devuelve todas las apps nuestras instaladas (permisos,
  routers); `module_configs()`, solo las de `kind = "app"` (menú, página de apps, foto del SaaS, y
  sus `setup`, `widgets` y `bell`); `declared_events()`, los eventos que declara la lista `ALL` del
  `events.py` de cada app nuestra (sin `events.py` o sin `ALL`, ninguno).
- **Checks** (`live.checks`, etiqueta `live`, registrados al arrancar la app `live`; corren con
  `manage.py check` y `runserver` y miran siempre todas las apps nuestras):
  - `live.E001`: `kind` no es `"platform"` ni `"app"`;
  - `live.E002`: un módulo sin `icon`;
  - `live.E003`: un módulo cuya `category` no es un `Category`;
  - `live.E004`: `requires` nombra algo que no es un módulo (una app de plataforma como `base`, o una
    etiqueta que no existe);
  - `live.E005`: un ciclo en `requires` (un error por ciclo);
  - `live.E006`: una app de plataforma no deja en su valor por defecto `requires`, `category`,
    `premium`, `navigation`, `summary`, `description`, `verticals`, `listed`, `setup`, `widgets` o
    `bell` (se compara con el valor por defecto, no con «verdadero»: `listed` vale `True`); los pasos
    de plataforma de `base` los pone `base.setup.status`, no su `LiveAppConfig`;
  - `live.E007`: un módulo sin `summary`, con un `summary` de más de una línea o de más de 120
    caracteres, sin `description` o con un `verbose_name` de más de 80 (medidos en inglés; el `es`
    lo valida `register_apps`);
  - `live.E008`: un id de `verticals` que no casa `^[a-z][a-z0-9]*(_[a-z0-9]+)*$`, pasa de 50
    caracteres (`hub_template_<vertical>` cabe en 63), es `test` (reservado) o se repite; o
    `verticals` no es una lista;
  - `live.E009`: `setup`, `widgets` o `bell` no es una lista (o tupla) de su dataclass;
  - `live.E010`: el `operation` de un paso, panel o contador no es una consulta (`kind="query"`)
    declarada del propio módulo (su prefijo es el `label`); un panel por `component` puede no tenerlo;
  - `live.E011`: su `permission` no es uno de los `permissions` del módulo (`None` = sin permiso);
  - `live.E012`: su `refresh_on` no es una lista, o nombra un evento que ningún `events.py` declara
    en `ALL` (`declared_events()`);
  - `live.E013`: una `key` que no casa `^[a-z][a-z0-9_]*$` o que se repite en su lista (la misma
    `key` en dos listas vale);
  - `live.E014`: un panel con `kind` y `component` a la vez, sin ninguno de los dos, con un `kind`
    que no está en `WIDGET_KINDS` o con `kind` y sin `operation`;
  - `live.E015`: un panel con un `size` que no es `sm`, `md` ni `lg`;
  - `live.E016`: un `configured_when` que no es una lista de `SetupCheck`, o una condición sin
    `field` o sin exactamente uno de `truthy` y `equals`.

  Los checks de los hooks necesitan las operaciones y los eventos registrados, cosa que
  `LiveConfig.ready` hace antes de cualquier check. La app de pruebas (`tests/testapp`) es un módulo
  (`kind = "app"`) con `icon`, `category`, `summary`, `description` y `verticals`, y un paso, un panel y
  un contador sobre su consulta `testapp.thing.list` y su evento `testapp.thing.created` (su
  `events.py`), para pasarlos.
- **Routers**: `live.ninja.mount_app_routers(api)` monta en la raíz de la API el `router` del `api.py`
  de toda app nuestra (de plataforma o módulo), en el orden de `INSTALLED_APPS`, y devuelve sus
  etiquetas; la que no tiene `api.py` se salta y un `api.py` sin un `Router` de ninja en `router` lanza
  `LiveMisuse`. Lo usa `hub-next/config/api.py`; `saas-next` lo adopta en su carril (PLAN §20.7).

## Catálogo compartido y markdown (ronda 16, PLAN §21)

- **`live.shared_catalog`**: el contrato del esquema `shared` de la BD `saas`. Modelos abstractos
  `AbstractApp` (`shared.app`) y `AbstractAppDoc` (`shared.app_doc`, clave UUIDv7, FK relativa a
  `App`) y las tablas citadas `APP_TABLE` y `APP_DOC_TABLE`. El SaaS los concreta como dueño
  (`saas-next/apps`, con la restricción `shared_app_doc_app_lang_unique` y sus migraciones) y el Hub
  como espejo `managed = False` (`hub-next/shared`). Cambiar una columna es expand/contract entre los
  dos repos; `tests/test_shared_catalog.py` fija las columnas.
- **`live.markdown.render_markdown(text, *, image_base="")`**: markdown a HTML limpio (`markdown` +
  `nh3`, la lista blanca del SaaS viejo), ```` ```mermaid ```` como `<pre class="mermaid">`, `id` en
  los títulos (`toc` con `slugify_unicode`) e imágenes solo de `docs/img/` de la app, reescritas a
  `image_base`; cualquier otro origen quita la `<img>` y sin `image_base` no queda ninguna.

## Slugs reservados

`live.slugs` es la **única** regla del slug de un hub (el primer rótulo de `<slug>.erplora.com`) y la
**única** lista de nombres reservados, para `hub-next` y `saas-next` (Ioan, 2026-10-13; PLAN §16.14).

- **Regla**: `HUB_SLUG_RE` (`^[a-z0-9]([a-z0-9-]{1,61}[a-z0-9])?$`): minúsculas, cifras y guiones, sin
  guion al principio ni al final; 3–63 caracteres; nunca empieza por `xn--` (punycode).
- **Reservados** (`RESERVED_HUB_SLUGS`): palabras de sistema. Los nuestros son `hubs` (host de
  plataforma: el admin del Hub para el staff, ronda 13, PLAN §18) y `pre` (entorno de preproducción
  del equipo: `pre.erplora.com` y sus hubs en `*.pre.erplora.com`, 2026-10-14); `hub` sigue reservado
  y el resto son nombres bloqueados para que ningún cliente los tome. Para añadir uno se edita esta lista, no se
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
