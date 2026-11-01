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
  output, expose_api=False, ai=…, database=True)`; `query` solo en `queries.py` (transacción `READ ONLY`,
  `statement_timeout` 5 s), `command` solo en `services.py`. Con `database=False` la operación no toca
  ninguna BD y corre **sin** transacción (lo que espera a la red, p. ej. la respuesta de otro servicio: la
  espera no retiene una conexión); conserva el permiso, el gancho `LIVE["operation_database"]` y la salida
  validada, y una consulta a cualquier BD, un evento o un `on_commit` dentro es `LiveMisuse`. Cada ruta ninja llama a `run_operation`
  con `operation_id` = nombre de la operación; OpenAPI en `/api/openapi.json` y Swagger en `/api/docs`.
  `ai=` es obligatorio (PLAN §30, `live.E017`): `AI(description=…, risk="normal"|"high", preview=None)` para una
  herramienta del asistente (la descripción, en inglés, es lo que lee el modelo; `high` pide teclear una palabra) o
  `INTERNAL` (centinela falso) para lo que no lo es. Un `dict` con `description` se sigue aceptando y
  `Operation.ai_spec()` lo lee como uno de los dos: sin descripción, con «Not an assistant tool…»/«System only…» o en
  una operación que solo corre la plataforma (sin permiso o con uno que ninguna app declara, `declared_permissions()`)
  es `INTERNAL`. Una herramienta dice además lo que una persona escribiría en el chat para pedirla: `AI(…, asks={"en":
  (…), "es": (…)})` (frases naturales y ambiguas, como las dice la gente: «créame un producto», «súbele el precio al
  café», «what did I sell today?»; nunca el nombre de la operación); el `dict` lo acepta en su clave `"asks"` y
  `live.assistant.asks_of(op)` lo lee de las dos formas, limpio (nada si `ai_spec()` es `INTERNAL`). La selección de herramientas las pesa y la QA del
  asistente sale de ellas (ver «Asistente»).
  Errores: `{"error": {"code", "message", "fields"?}}`; 422 `invalid_payload` con `fields`. El 404 de
  una ruta inexistente y el 405 de método equivocado (no llegan a ninguna ruta) los convierte al mismo
  sobre `live.api_errors.ApiErrorEnvelopeMiddleware` (en `MIDDLEWARE` tras auth), bajo
  `LIVE["api_prefix"]` (`/api/` por defecto); no toca JSON, streams, `/api/live` ni `/api/docs`. Los
  mensajes salen en el idioma de la petición (HTTP) o del stream (`ctx.language`, en `/api/live`).
- **Transacciones anidadas** (`live.operations.atomic`, `current_alias`): lo que un `services.py` envuelve en un
  savepoint va con `atomic()` (gestor de contexto o decorador, `savepoint` y `durable` como en Django), nunca con un
  `transaction.atomic()` desnudo, cuyo alias es `default`: con `LIVE["operation_database"]` la transacción de la
  operación no está en `default` (hub-next, fase 2: la BD del hub) y un `try: with transaction.atomic(): create…
  except IntegrityError:` abriría otra transacción en `default` y el error abortaría la de la operación. `atomic()`
  abre en `current_alias()`: lo que dice `LIVE["current_database"]` (ruta a una función sin argumentos; hub-next:
  `base.tenancy.context.current_alias`, el alias del `use_hub` activo y `HubContextMissing` sin contexto, nunca
  `default` por omisión), si no el alias de la operación en curso y, fuera de una, `default` (el SaaS, sin tenencia).
  Dentro de una operación `database=False` es `LiveMisuse`. Lo lee al entrar en el bloque (un decorador, en cada
  llamada).
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
- **Eventos de fin de sesión** (`LIVE["session_events"]`, opcional; FIX-LIVE-SESSION-CLOSED-WAKES-ONLY-SESSION-LIST):
  los eventos que pueden haber terminado la sesión con la que se abrió un stream (en `saas-next`,
  `accounts.session.closed`: salir, una contraseña nueva, «Cerrar las demás sesiones»). Ninguna consulta viva tiene
  que declararlos: al llegar uno al canal, cada stream relee su contexto una vez (el `refresh` del builder, en el
  mismo hilo, idioma y `enter` que una re-ejecución) y se cierra con `bye` si lanza `Unauthorized`; sus consultas no
  se re-ejecutan por él. Una ráfaga sigue siendo una pasada, y si en esa pasada se re-ejecuta alguna consulta (la que
  sí lo declara), su `refresh` es la relectura. Se nombran uno a uno, nunca por su forma: en `hub-next`,
  `cash_register.session.closed` y `table.session.closed` son de caja y de mesa. El Hub no lo usa: al revocar
  sesiones despierta con `"*"` (`ALL_EVENTS`), que re-ejecuta todo.
- **SPA y CSP**: `live.spa` lee el manifiesto de Vite (sin django-vite) y emite `<script type=module>` y
  `modulepreload` con nonce; en DEBUG apunta al servidor de Vite. `spa_assets(request, entry=…)` da
  otra entrada del mismo build (p. ej. `frontend/public.ts`, la web pública de `saas-next`, ronda 16);
  sin `entry`, la de `LIVE["spa"]["entry"]`. `LIVE["spa"]["icons"]` (opcional) declara los iconos de la
  pestaña y de la pantalla de inicio (`{"rel": "icon" | "apple-touch-icon", "path": <estático>, "sizes"?}`),
  enlazados por el almacén de estáticos del proyecto y nunca por URL; sin él, ningún `<link>` (sin icono, el
  navegador pide `/favicon.ico`). `live.csp`: nonce + `strict-dynamic` +
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
- **Solo un módulo, para los avisos del dispositivo** (ronda PLAN-HUB 2026-10-23; los rellena `base`
  con `base.notice.list` y la shell los da una vez por dispositivo con el aviso del sistema de la app
  nativa): `notices: list[DeviceNotice]`, vacía por defecto. `key`, `operation` (una consulta de su
  propio `queries.py` cuyas `rows` dicen qué pasó, lo más nuevo primero, cada una con `id` y el
  instante `at`), `title` (lista de plantillas de `str.format` sobre los campos de la fila; gana la
  primera con todos sus campos rellenos) y `route` (la pantalla que abre el toque, también plantilla),
  obligatorios; `body` (partes que se juntan con « · », las que tengan todos sus campos rellenos),
  `when` (lista de `SetupCheck` sobre la fila: solo las filas que las cumplen son de este aviso),
  `params`, `permission` y `refresh_on`.
- **Lectura**: `all_live_app_configs()` devuelve todas las apps nuestras instaladas (permisos,
  routers); `module_configs()`, solo las de `kind = "app"` (menú, página de apps, foto del SaaS, y
  sus `setup`, `widgets`, `bell` y `notices`); `declared_events()`, los eventos que declara la lista `ALL` del
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
    `premium`, `navigation`, `summary`, `description`, `verticals`, `listed`, `setup`, `widgets`,
    `bell` o `notices` (se compara con el valor por defecto, no con «verdadero»: `listed` vale `True`); los pasos
    de plataforma de `base` los pone `base.setup.status`, no su `LiveAppConfig`;
  - `live.E007`: un módulo sin `summary`, con un `summary` de más de una línea o de más de 120
    caracteres, sin `description` o con un `verbose_name` de más de 80 (medidos en inglés; el `es`
    lo valida `register_apps`);
  - `live.E008`: un id de `verticals` que no casa `^[a-z][a-z0-9]*(_[a-z0-9]+)*$`, pasa de 50
    caracteres (`hub_template_<vertical>` cabe en 63), es `test` (reservado) o se repite; o
    `verticals` no es una lista;
  - `live.E009`: `setup`, `widgets`, `bell` o `notices` no es una lista (o tupla) de su dataclass;
  - `live.E010`: el `operation` de un paso, panel, contador o aviso no es una consulta (`kind="query"`)
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
    `field` o sin exactamente uno de `truthy` y `equals`;
  - `live.E018`: un aviso del dispositivo cuya consulta no responde una lista `rows` (o `items`) de
    filas con `id` y `at`; un `title` vacío o que no es una lista de textos, un `body` que no es una
    lista de textos, una `route` que no empieza por `/` (o empieza por `//`); una plantilla rota, con
    un campo posicional, anidado, con atributo o índice, o que nombra un campo que la fila no tiene
    (medidas en inglés); o un `when` que no es una lista de `SetupCheck`, o una condición sin
    exactamente uno de `truthy` y `equals` o sobre un campo que la fila no tiene;
  - `live.E017`: una operación registrada sin `ai=`, con un `AI` o un `dict` sin descripción, con un `risk` que no
    es `normal` ni `high`, o con algo que no es `AI`, `INTERNAL` ni un `dict` (ronda 2026-10-22b, PLAN §30);
  - `live.E019`: `LIVE["session_events"]` no es una lista (o tupla), o nombra algo que no es un evento que declare
    la lista `ALL` de algún `events.py` (`declared_events()`; `"*"` tampoco).
  - `live.E020`: una herramienta (`AI`, nunca `INTERNAL`) de una app listada en el ajuste de Django
    `LIVE_ASSISTANT_ASKS_REQUIRED` (tupla de etiquetas; por defecto `()`) sin `asks` en `en` y en `es` con al menos
    `MIN_ASKS` (2) frases distintas cada uno (sin contar mayúsculas ni espacios), o con una frase vacía, que no es
    texto, igual a su propio nombre (el de la operación o el de la herramienta) o de más de `MAX_ASK_CHARS` (120)
    caracteres; o el propio ajuste que no es una tupla de etiquetas o que nombra una app sin operaciones (una errata
    dejaría pasar todo). Una app se lista cuando todas sus herramientas las dicen: los cientos del Hub no se migran de
    una vez. `live.E017` no cambia.

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

## Asistente (`live.assistant`, PLAN §30 y plan 2026-10-30 del asistente del SaaS §2)

Las mecánicas del asistente que no dependen de la pasarela, las mismas en el Hub y en el panel del SaaS:
`catalog(ctx, active_labels=…, not_from_chat=…, approvable=…)` (las herramientas de la persona: operaciones con
`AI`, de las apps encendidas, con su permiso), `relevant(tools, texts, language, always=…, app_words=…, synonyms=…,
howto=…)` (como mucho `MAX_TOOLS`, sin modelo ni red: las raíces de las palabras de la pregunta en español o inglés,
`stem`/`stems`, con sus sinónimos del negocio, `SYNONYMS`, contra la app, el nombre, la descripción y los datos que toma
cada herramienta; pesa más la acción pedida, `VERBS`, sobre la cosa que se nombra; live#16; detalle abajo), `tool_spec`, `card(op, arguments, language,
words)` (la tarjeta de una escritura) con `confirmed` y `CONFIRM_WORD`, `invalid_arguments` (los datos que la operación
rechazaría vuelven al modelo antes de dibujar la tarjeta, salvo la escritura peligrosa que no nombra registros,
`blocked`; live#17), `run_tool` (ejecuta como la persona, resultado cortado en `MAX_RESULT_CHARS`), `preview` (la
lectura que nombra `AI.preview`) y `rounds`/`MAX_ROUNDS`. Cada proyecto dice los datos con sus palabras (`Words`: momento,
registro, importe, nombre de la app); `PlainWords` no lee nada (euros con 2 decimales, UTC con los formatos de
Django del idioma, el registro fuera de la tarjeta). Las del Hub (zona y moneda del negocio, `refers`) viven en su
`base/assistant.py`.

`relevant` pesa lo que la gente dice para pedir una herramienta (sus `asks`, en cualquier idioma) como su descripción:
1 por cosa nombrada.

**Cómo lee una frase** (`asked(texts, synonyms)` → `Asked`; todo determinista y en milisegundos con ~750 herramientas):

- **Raíces** (`stem`): un imperativo con sus pronombres es su verbo («cóbrale», «súbele», «dime», «descárgame» →
  «cobra», «sube», «di», «descarga»); un verbo guarda raíz de tres letras («sube», «subir» → «sub»); un verbo inglés
  pierde la consonante doblada con su final («tagged» → «tag»). Las palabras de dos cosas no comparten raíz: «tablet» no
  es «table», «compartido» no es «company», «peluquería» no es «peluquero», «carta» no es «cart», «contrato» y
  «contraseña» no son «control», «recibo» no es «recibir», «registro» no es «register», «settings» no es «set», y «ficha»
  (la del cliente) no es «fichar» salvo al empezar una orden («ficha la entrada de Ana»; igual «reserva una mesa»).
- **Verbos** (`VERBS`): una frase de varias palabras cuenta seguida y sus palabras no piden otra cosa («get rid of» es
  borrar, nunca `get`; «set up» configura, nunca `set`; «add up» y «¿cuadran?» comprueban, no añaden; «cambia el
  nombre» y «ponle de nombre» renombran). «Ponle», «añade», «apunta» y «mete» añaden (`add`); «exporta», «descarga»,
  «download» exportan; «importa», «súbeme», «upload» importan; «borremos todos sus datos» y «erase» borran del todo
  (`erase`); «empieza» y «start» abren; «ponme la app», «instala» encienden; «how many» y «cuántos» cuentan (`count`, `list`, `stats`). «How», «which»,
  «cómo» y «cuál» ya no son el verbo «listar». Un verbo no nombra cosas salvo por sus sinónimos («cobra» nombra la
  venta; «show me», «dame», «dime», «give me», «tell me» no nombran nada).
- **Preguntas**: una pregunta (palabra interrogativa con tilde, que empieza por una o por un auxiliar inglés, o con sus
  signos) pide saber aunque nombre un verbo («do I need a customer to charge?»): sus lecturas van primero y lo que nombra
  ese verbo es de lo que pregunta (`Asked.about`: «what can customers pay with?» → las formas de pago). Nunca es pregunta
  una frase que es una orden: tras saludos y palabras de petición empieza por un verbo que hace algo («hola, ¿puedes
  cobrar la mesa 4?», «hey charge table 4?», «cobra la mesa 4 y dime cuánto es», «do a refund»). Un «que» sin tilde solo
  pregunta con signos («dice que sí», «anula el ticket, que me equivoqué» no preguntan). «Can you…?» y «¿puedes…?» son
  peticiones: piden hacer. El texto se normaliza (NFC) antes de buscar las tildes.
- **Cómo se hace**: «how do I…», «¿cómo se…?», «¿cómo invito…?», también tras «dime», «explícame» o «tell me»
  («tell me how to…»), dan `HOWTO_POINTS` a las herramientas de `howto=`, la
  búsqueda en la documentación de cada proyecto (Hub `base.docs.search`, SaaS `assistant.docs.search`): llega por ser
  una pregunta de cómo se hace, no solo por estar en `ALWAYS`.
- **Pesos**: una cosa nombrada vale 2 en la entidad de la herramienta o en lo que su acción toca (`create_folder` toca
  una carpeta; lo que va tras `for`/`by`/`from` solo dice para qué, 1), y 1 si solo nombra su app: el nombre de una app
  desempata, nunca ahoga lo pedido («customers» ya no da puntos a toda la app de clientes). Si la pregunta no nombra la
  cosa de ninguna herramienta, la app nombrada por su nombre es la cosa de sus herramientas («¿qué hay en la cocina?»,
  «abre la caja con 100 €»); al lado de una cosa nombrada («el registro de eventos») solo desempata. La acción pedida sobre la
  cosa nombrada suma 9, y 3 más si esa cosa es lo primero que nombra la orden desde su verbo (`Asked.objects`: «crea la
  carpeta Facturas» crea una carpeta, no una factura); una escritura de otra cosa no suma si alguna herramienta hace
  eso a lo que la orden toca («reserva una mesa» no trae las altas de la plantilla; «create a 10% discount» sí trae las
  altas, porque ninguna herramienta crea un descuento); una lectura sin cosa nombrada suma 1 solo si se nombra su app
  (los «cuántos» no levantan todas las listas), y un dato por el que filtra no es lo que lee. Encender o apagar algo
  que una escritura toma la cambia («turn off the alerts» → `accounts.preferences.update`); una escritura de una cosa
  nombrada tras el verbo trae la lectura que la encuentra («borra el cliente Ana»).
- **Sinónimos del proyecto** (`synonyms=`): `SYNONYMS` guarda solo lo que una palabra significa en cualquier negocio.
  Lo que significa solo en un proyecto lo pasa ese proyecto en cada turno y en su QA, nunca se fija en `live`: «cuenta»
  es la cuenta de una mesa en el Hub (`(("cuenta", "check", "tab", "order"),)`) y la cuenta de la persona en el SaaS
  (`(("cuenta", "account"),)`). Un grupo admite frases («foto de perfil»).

**QA del asistente, derivada de las operaciones** (`live.assistant_qa`; plan 2026-10-31 del conocimiento y la QA del
asistente), en dos capas:

1. **Determinista, en cada PR** (sin modelo ni red): `misses(tools, *, language, top=10, app_words=…, always=…,
   synonyms=…, howto=…, own_asks=True)` pasa cada `ask` del idioma de cada herramienta del catálogo por el mismo
   `relevant` de un turno (con las `always`, `app_words`, `synonyms` y `howto` del proyecto) y devuelve, ordenadas por
   herramienta y frase, las `Miss(tool_name, ask, position)` cuya herramienta no sale entre las `top` primeras
   (`position` desde 1, o `None` si ni se ofrece; `top` entre 1 y `MAX_TOOLS`). Las funciones leen `language` sin región
   (`base_language`: `es-ES` → `es`). `relevant` lee las `asks` de cada herramienta una vez por operación (caché), no en
   cada turno. `uncovered(tools, language)` lista, ordenadas, las herramientas sin `asks` en ese idioma.
   Con `own_asks=True` la frase cuenta para su propia herramienta, así que llega diga lo que diga (cambiar las `asks`
   de una herramienta por palabras sin relación sigue pasando). **Los tests por app usan `own_asks=False`**: cada frase
   se ordena sin ella misma (la herramienta conserva sus otras `asks` y su descripción, como encontraría la frase nueva
   de una persona), así se mide que las frases generalizan. `report(tools, language, top=10, *, app_words=…,
   always=…, synonyms=…, howto=…)` da, por herramienta y ordenado, un `Reach(tool_name, asks, own, unseen, own_within,
   unseen_within)`: la posición de cada frase con su propia frase y sin ella, y cuántas entran en las `top` primeras de
   cada modo, para el resumen de cobertura del test. Esta capa prueba que las frases de la gente llegan a la
   herramienta entre cientos, no que el modelo la llame.
2. **Con el modelo real** (Playwright en el Hub y el SaaS): `export_catalog(tools, language)` da cada herramienta,
   por nombre y serializable a JSON, con `name`, `tool_name`, `app_label`, `kind` (`read`/`write`), `permission`,
   `risk`, `description`, `asks` (las del idioma) e `input_schema`; de ahí la QA escribe sus propias frases por rol.

El Hub y el SaaS las llaman con su catálogo real (`catalog(ctx, …)`) como cada rol: lo que un rol no puede hacer ni
está en su catálogo.

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

## reCAPTCHA Enterprise (formularios públicos)

`live.recaptcha` comprueba que quien envía un formulario público es una persona, con reCAPTCHA Enterprise por
puntuación: invisible, sin casilla ni puzle (Ioan, 2026-10-22). Hoy lo usa el SaaS.

- **Ajustes** (`LIVE["recaptcha"]`): `enabled` (apagado por defecto), `project` (`erplora`), `site_key` (pública,
  la que carga `enterprise.js`), `api_key` (secreta, la de la API REST de las evaluaciones; nunca va al registro),
  `min_score` (0–1, por defecto 0.5), `fail_open_on_unavailable` (las acciones que dejan pasar cuando no se puede
  preguntar a Google; por defecto `login`, `login_code` y `mfa_authenticate`) y `endpoint` (opcional; por defecto
  el de Google para `project`). Encendido sin `project`, `site_key` o `api_key`, con `min_score` fuera de 0–1 o con
  `fail_open_on_unavailable` que no sea un conjunto de nombres, es `LiveMisuse`.
- **`verify_or_raise(request, token, action)`**: pide a Google la evaluación del token (`assess`, `urllib`, 5 s
  como mucho, con la dirección y el navegador del visitante) y devuelve la `Assessment(score, valid,
  action_matches, reasons)` o lanza `RecaptchaFailed` (400 `recaptcha_failed`, mensaje en `en` + `es`, el sobre
  de la API). Rechaza sin token (sin llamar a Google), token no válido, token de otra acción y puntuación por debajo
  de `min_score`. Si no se puede preguntar a Google (tiempo agotado, red, 5xx, respuesta ilegible; un 4xx también,
  con CRITICAL `recaptcha.misconfigured`: clave, cuota o facturación), falla cerrado salvo en las acciones de
  `fail_open_on_unavailable`: la entrada y sus segundos factores, que ya protegen la contraseña o el código y sus
  límites, pasan con un ERROR `recaptcha.unavailable` y una cuenta por acción (`unavailable_counts()`), para que una
  caída de Google no deje fuera a nadie, tampoco al personal. Un veredicto de Google sigue rechazando ahí. Apagado,
  deja pasar todo y lo avisa una vez por proceso.
- **`site_key()`**: la clave pública para la página, vacía si está apagado (sin script ni token).
- **`with_recaptcha(policy)`**: una copia de la CSP con lo que piden los scripts de Google (`script-src`
  `www.google.com/recaptcha/` y `www.gstatic.com/recaptcha/`, `frame-src` `www.google.com/recaptcha/` y
  `recaptcha.google.com/recaptcha/`, `connect-src` `www.google.com/recaptcha/`) y, si la política tiene Trusted
  Types, la política `goog#html` que crea su script.

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
