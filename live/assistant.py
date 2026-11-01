"""The assistant's mechanics that do not depend on a gateway (PLAN §30; docs/plans/2026-10-30-asistente-saas.md §2):
the Hub's assistant and the SaaS's panel use the same ones, each with its own tools and its own words.

- **Its tools** (``catalog``) are the operations of the apps on (``active_labels``) that this person may run (the
  operation's own permission), told to the model by their ``ai=`` (``is_tool``: an ``AI``, never ``INTERNAL``) and
  never what the project keeps out of the chat (``not_from_chat``). A turn offers only the few of what was asked
  (``relevant``, at most ``MAX_TOOLS``), never the whole catalogue. A tool runs as the person, by its own operation
  (``run_tool``): the same permission, transaction and refusals as the button on the screen.
- **A write never runs without the person's yes**: its card (``card``) says what it will send, each datum by its name
  in the person's language (the title its schema gives it, else the name its app's models give that field: their
  metadata, no query) and in words (``Words``: a moment, a record, an amount, as the project says them; a value of a
  closed list by the label its app's models give it); a secret hidden; an attempt key left out. ``risk="high"`` asks to
  type a word in the person's language (``CONFIRM_WORD``) or, over records named by ``ids``, how many; such a write
  that names no record is not done from the chat (``blocked``). Such a write may show what it will do (``preview``): a
  read of its own app its ``ai=`` names, run as the person before the card. A card is drawn only for data its operation
  takes (``invalid_arguments``): what it would refuse goes back to the model, which asks again with it corrected.
- **Words** (``Words``): the project says a moment, a record and an amount its own way (the Hub: at its business's
  hour, by the read a schema marks, in its business's currency); ``PlainWords`` reads nothing — amounts in euros with
  two decimals, moments at UTC as Django's formats of the language write them, a record left out.
"""

import datetime as dt
import json
import re
import unicodedata
import uuid
from collections.abc import Callable, Collection, Iterable, Mapping
from dataclasses import dataclass
from functools import cache, lru_cache
from typing import Any, NamedTuple, Protocol

import pydantic
from django.conf import settings
from django.core.exceptions import FieldDoesNotExist
from django.utils import formats, translation
from django.utils.text import capfirst
from django.utils.translation import gettext, pgettext_lazy

from live.context import OperationContext
from live.errors import AppInactive, OperationError, PermissionDenied, Unauthorized
from live.meta import LiveAppConfig, all_live_app_configs
from live.operations import AI, Operation, registry

#: The tools a turn offers at most: the gateway takes 256, the model chooses better among a few.
MAX_TOOLS = 40
#: Rounds of tools of one request of the person (the old hub's guard against a loop, not an allowance).
MAX_ROUNDS = 6
#: A tool's result told back to the model: no more (a list of a hundred rows fits).
MAX_RESULT_CHARS = 60_000
SEPARATOR = "__"
#: What a dangerous write asks to type, in the person's language.
CONFIRM_WORD = pgettext_lazy("assistant", "CONFIRM")


# ── Tools ────────────────────────────────────────────────────────────────────────────────────────────────────────


def tool_name(operation_name: str) -> str:
    """The operation's name as a tool's (the gateway's function names take no dots)."""
    return operation_name.replace(".", SEPARATOR)


def operation_of(name: str, tools: dict[str, Operation]) -> Operation | None:
    """The operation of the tool ``name`` among ``tools``; ``None`` for one it was not offered."""
    for op in tools.values():
        if tool_name(op.name) == name:
            return op
    return None


def named(name: str) -> Operation | None:
    """The registered operation the tool ``name`` stands for, offered or not: only to name it in a receipt («Not done,
    not allowed: Create in Demo»); it never runs from here."""
    return operation_of(name, registry)


def description(op: Operation) -> str:
    """What ``op``'s ``ai=`` tells the model it does (a ``dict``'s as written, «Not an assistant tool…» too); ``""``
    when it declares none or ``INTERNAL``."""
    declared = op.ai
    if isinstance(declared, AI):
        return declared.description.strip()
    return str(declared.get("description", "")).strip() if isinstance(declared, dict) else ""


def risk(op: Operation) -> str:
    """``high`` when ``op``'s ``ai=`` says so (a ``dict``'s too, tool or not: an automation never runs it alone),
    ``normal`` otherwise."""
    declared = op.ai
    said = declared.risk if isinstance(declared, AI) else declared.get("risk") if isinstance(declared, dict) else None
    return "high" if said == "high" else "normal"


def preview_of(op: Operation) -> Any:
    """What ``op``'s ``ai=`` declares as its preview, or ``None``."""
    declared = op.ai
    if isinstance(declared, AI):
        return declared.preview
    return declared.get("preview") if isinstance(declared, dict) else None


def asks_of(op: Operation) -> dict[str, tuple[str, ...]]:
    """What a person would type to ask for ``op``, by language, as its ``ai=`` says it (an ``AI``'s or a ``dict``'s
    ``asks``): each phrase stripped, an empty or repeated one left out, a lone phrase read as one; a language with none
    left, anything that is not a mapping of language → phrases and what is no tool (``Operation.ai_spec``: never
    offered, so nothing asks for it) read as nothing."""
    spec = op.ai_spec()
    said = spec.asks if isinstance(spec, AI) else None
    if not isinstance(said, Mapping):
        return {}
    asks: dict[str, tuple[str, ...]] = {}
    for language, phrases in said.items():
        if isinstance(phrases, str):
            phrases = (phrases,)
        if not isinstance(language, str) or not isinstance(phrases, list | tuple):
            continue
        kept = tuple(dict.fromkeys(phrase.strip() for phrase in phrases if isinstance(phrase, str) and phrase.strip()))
        if kept:
            asks[language] = kept
    return asks


def is_tool(op: Operation, *, not_from_chat: Collection[str] = frozenset()) -> bool:
    """Whether ``op`` is an assistant tool: its ``ai=`` is one (``Operation.ai_spec``) and the project does not keep it
    out of the chat (``not_from_chat``: emptying the business, a file to download)."""
    return isinstance(op.ai_spec(), AI) and op.name not in not_from_chat


def catalog(
    ctx: OperationContext,
    *,
    active_labels: Collection[str],
    not_from_chat: Collection[str] = frozenset(),
    approvable: Callable[[Operation], bool] | None = None,
) -> dict[str, Operation]:
    """The tools of ``ctx``'s person among the apps ``active_labels``: by name, in name order. A write someone else may
    approve (``approvable``) is theirs too, as its button on the screen is: running it asks for the approval."""
    return {
        name: op
        for name, op in sorted(registry.items())
        if op.app_label in active_labels
        and is_tool(op, not_from_chat=not_from_chat)
        and (ctx.has(op.permission) or (approvable is not None and approvable(op)))
    }


# ── By relevance ─────────────────────────────────────────────────────────────────────────────────────────────────
#
# A turn offers the few tools of what was asked (``relevant``), chosen with no model nor network: the words of the
# question, cut to their stems (``stem``: «vendí», «vendido» and «vender» are one; «cóbrale» is «cobra»), each with the
# words that name the same thing (``SYNONYMS``, and the project's own: «cuenta» is a check in the Hub, the account in
# the SaaS), against each tool's app (its names in both languages), the parts of its name, its ``ai=`` description and
# what people say to ask for it (its ``asks``); the action asked (``VERBS``) of the thing named weighs most. A question
# asks to know: its reads come first, and the action it names without asking for it («what can customers pay with?»)
# is what it asks about; a how-to question («how do I…?») is answered from the help (``howto``). The same question
# always gets the same tools.

#: What a person says (Spanish or English) → the action of the operations that does it: the last part of an
#: operation's name or one of its words (``bulk_create``, ``set_image``). A phrase counts when its words come in a row,
#: and its words then ask for no other action and name nothing (``_PHRASE_NAMES`` aside): «get rid of» is no ``get``,
#: «set up» no ``set``, «turn on» no «turno».
VERBS = {
    "create": ("crea", "crear", "creame", "alta", "anade", "anadir", "agrega", "agregar", "apunta", "apuntar",
               "registra", "registrar", "reservar", "nuevo", "nueva", "add", "create", "new", "register", "book"),
    "add": ("anade", "anadir", "agrega", "agregar", "apunta", "apuntar", "mete", "meter", "ponle", "add"),
    "update": ("cambia", "cambiar", "modifica", "modificar", "actualiza", "actualizar", "edita", "editar", "pon",
               "ponle", "poner", "sube", "subir", "configura", "configurar", "ajusta", "ajustar", "update", "change",
               "edit", "set", "set up", "configure", "cambia el nombre", "cambiale el nombre", "cambiar el nombre",
               "ponle de nombre", "ponle el nombre", "ponle nombre", "pon de nombre", "change the name",
               "change its name"),
    "change": ("cambia", "cambiar", "change"),
    "rename": ("renombra", "renombrar", "rename", "cambia el nombre", "cambiale el nombre", "cambiar el nombre",
               "ponle de nombre", "ponle el nombre", "ponle nombre", "pon de nombre", "change the name",
               "change its name"),
    "set": ("pon", "ponle", "poner", "asigna", "asignar", "cambia", "cambiar", "ponle de nombre", "ponle el nombre",
            "ponle nombre", "pon de nombre", "set", "assign", "change"),
    "delete": ("borra", "borrar", "borremos", "borrad", "elimina", "eliminar", "quita", "quitar", "delete", "remove",
               "get rid"),
    "remove": ("borra", "borrar", "borremos", "borrad", "elimina", "eliminar", "quita", "quitar", "delete", "remove",
               "get rid"),
    "erase": ("erase", "wipe", "borra sus datos", "borra todos sus datos", "borra los datos", "borrar sus datos",
              "borrar todos sus datos", "borrar los datos", "borrad todos sus datos", "borremos todos sus datos",
              "borremos sus datos"),
    "list": ("lista", "listar", "muestra", "muestrame", "ensena", "ensename", "ver", "dime", "cuantos", "cuantas",
             "busca", "buscar", "list", "show", "find", "search", "how many"),
    "count": ("cuantos", "cuantas", "contar", "count", "how many"),
    "get": ("dame", "datos", "detalle", "get", "detail"),
    "check": ("cuadra", "cuadran", "cuadrar", "cuadre", "comprueba", "comprobar", "reconcilia", "add up", "adds up",
              "reconcile"),
    "stats": ("cuadra", "cuadran", "cuadrar", "cuadre", "cuantos", "cuantas", "add up", "adds up", "how many"),
    "export": ("exporta", "exportar", "descarga", "descargar", "saca", "sacar", "export", "download"),
    "import": ("importa", "importar", "sube", "subir", "subeme", "import", "upload"),
    "upload": ("sube", "subir", "subeme", "upload"),
    "complete": ("cobra", "cobrar", "paga", "pagar", "charge", "pay"),
    "void": ("anula", "anular", "void"),
    "cancel": ("cancela", "cancelar", "anula", "anular", "cancel"),
    "close": ("cierra", "cerrar", "close"),
    "open": ("abre", "abrir", "empieza", "inicia", "open", "start", "begin"),
    "start": ("empieza", "inicia", "start", "begin"),
    "enable": ("activa", "activar", "activame", "enciende", "encender", "habilita", "habilitar", "enable", "activate",
               "turn on", "switch on", "quiero el modulo", "quiero la app", "quiero la aplicacion", "pon la app",
               "ponme la app", "pon el modulo", "ponme el modulo", "instala", "instalar", "install"),
    "disable": ("desactiva", "desactivar", "apaga", "apagar", "deshabilita", "deshabilitar", "disable", "deactivate",
                "turn off", "switch off"),
    "invite": ("invita", "invitar", "invite"),
    "print": ("imprime", "imprimir", "saca", "sacar", "print"),
    "refund": ("devuelve", "devolver", "reembolsa", "reembolsar", "refund"),
}
#: The words of a verb's phrase that still name what they name: «cambia el nombre» changes a name.
_PHRASE_NAMES = frozenset({"nombre", "name", "datos", "modulo", "app", "aplicacion"})
#: The actions that only read: a question that asks for none of the others asks to know, not to do. Asked of nothing
#: named, they bring no tool: «¿cuántos…?» is no list of everything.
READ_VERBS = frozenset({"list", "get", "count", "check", "stats"})
#: The actions that turn something on or off: of a setting a write takes («turn off the alerts»), they change it.
SWITCHES = frozenset({"enable", "disable"})
#: The actions that change what a write takes.
_CHANGES = frozenset({"update", "set"})
#: Words of ``VERBS`` that name a thing, not an action of it: no verb's stem.
_NOT_VERBS = frozenset({"alta", "nuevo", "nueva", "new", "datos", "detalle", "detail"})
#: Verbs whose stem joins forms ``VERBS`` does not list, and the irregular ones («haz» is «hacer», «di» is «decir»).
_OTHER_VERBS = frozenset({"hacer", "decir"})
_IRREGULAR = {"haz": "hac", "di": "dec"}
#: The pronouns a Spanish command carries at its end («cóbrale», «dímelo», «quítaselos»), longest first. «te» and a
#: lone «se» are left out: an English verb ends in them («create») and an assistant is not asked to do it to itself.
_ENCLITICS = ("selos", "selas", "melos", "melas", "noslo", "nosla", "selo", "sela", "melo", "mela", "les", "los",
              "las", "nos", "le", "lo", "la", "me")
#: Words that end like a command with its pronouns and are none: «iniciales» (initials) is no «inicia» + «les».
_NOT_COMMANDS = frozenset({"iniciales"})
#: The words that ask something at the start of a sentence; with an accent («qué», «cómo») anywhere.
QUESTION_WORDS = frozenset(
    {"que", "cual", "cuales", "cuanto", "cuanta", "cuantos", "cuantas", "quien", "quienes", "como", "what", "which",
     "who", "whom", "how", "why"}
)
_INTERROGATIVE = re.compile(r"\b(?:qué|cuál|cuáles|cuánt[oa]s?|quién(?:es)?|dónde|cuándo|cómo)\b")
#: The English words a yes/no question starts with.
_AUXILIARIES = frozenset({"do", "does", "did", "is", "are", "was", "were", "can", "could", "should", "will", "would",
                          "have", "has", "am", "must", "may", "shall"})
#: Words a sentence may start with before what it says: greetings and fillers («hola, ¿puedes…?», «hey, delete…»).
_GREETINGS = frozenset({"hola", "hey", "hi", "hello", "oye", "vale", "ok", "okay", "bueno", "venga", "porfa", "buenas"})
#: Words before a how-to question that only ask for it («dime cómo…», «tell me how to…»).
_HOW_TO_LEADS = frozenset({"dime", "explicame", "ensename", "sabes", "tell", "explain", "show", "me", "us", "please"})
#: Articles an English command puts between «do» and what it does («do a refund»).
_ARTICLES = frozenset({"a", "an", "the", "un", "una", "el", "la"})
#: How a question that asks to do starts («can you charge table 4?»): a request, not a question.
_REQUESTS = frozenset({("can", "you"), ("could", "you"), ("would", "you"), ("will", "you"), ("me", "puedes"),
                       ("me", "podrias"), ("nos", "puedes"), ("please",), ("puedes",), ("podrias",), ("por", "favor")})
#: How a how-to question goes on after «how» / «cómo» / «where» / «dónde»: «how do I…», «¿cómo se…?», «¿cómo invito…?»
#: (any first person in «-o»), «where can I…».
_HOW_TO = {
    "how": frozenset({"do", "does", "can", "to", "should", "would", "could", "shall"}),
    "where": frozenset({"do", "can"}),
    "como": frozenset({"se", "puedo", "podemos", "puede", "pueden", "hago", "hacemos", "hay", "funciona", "funcionan",
                       "debo", "debemos", "tengo", "tenemos"}),
    "donde": frozenset({"se", "puedo", "esta", "estan", "encuentro", "veo"}),
}
_CLITICS = frozenset({"lo", "la", "le", "los", "las", "les", "me", "te", "nos"})
#: Points of the help (``howto``) for a how-to question: as much as an action asked of the thing named.
HOWTO_POINTS = 9
#: Words that name nothing by themselves (articles, pronouns, question words, the commonest verbs; Spanish and
#: English): no word of a tool.
STOP_WORDS = frozenset(
    {
        "que", "como", "cual", "cuales", "cuanto", "cuanta", "cuantos", "cuantas", "quien", "quienes", "donde",
        "cuando", "con", "sin", "por", "para", "del", "los", "las", "una", "uno", "unos", "unas", "mis", "tus", "sus",
        "nuestro", "nuestra", "este", "esta", "esto", "estos", "estas", "ese", "esa", "eso", "esos", "esas", "aqui",
        "alli", "hay", "tengo", "tiene", "tienen", "tienes", "tenemos", "hace", "hago", "hice", "son", "soy", "fue",
        "era", "muy", "mas", "pero", "porque", "todo", "toda", "todos", "todas", "puedo", "puede", "quiero", "favor",
        "algo",
        "the", "and", "for", "with", "what", "which", "who", "whom", "where", "when", "how", "this", "that", "these",
        "those", "its", "his", "her", "our", "your", "you", "are", "was", "were", "has", "have", "had", "did", "does",
        "can", "could", "would", "will", "one", "all", "any", "from", "into", "not", "but", "much", "many", "please",
        "there", "here", "some", "about", "want", "need",
    }
)
#: Words of one thing of a business, as people say it in Spanish or English and as the operations name it: one of
#: them asked asks for all. Only what stems cannot join («empleado» and ``staff``, «vendí» and ``sale``, «hoy» and
#: «today»); a phrase («foto de perfil») counts when its words come in a row. A project adds its own
#: (``relevant``'s ``synonyms``): what a word names there and nowhere else («cuenta»).
SYNONYMS = (
    ("empleado", "empleada", "trabajador", "trabajadora", "trabajar", "personal", "equipo", "cajero", "cajera",
     "camarero", "camarera", "dependiente", "dependienta", "profesional", "peluquero", "peluquera", "estilista",
     "employee", "worker", "staff", "member", "team", "cashier", "waiter", "waitress", "professional", "stylist"),
    ("venta", "vender", "vendido", "cobrar", "cobro", "recaudacion", "sale", "sell", "sold", "charge", "revenue",
     "takings"),
    ("hoy", "today"),
    ("ayer", "yesterday"),
    ("semana", "week"),
    ("mes", "meses", "mensual", "month", "monthly"),
    ("cliente", "customer", "client"),
    ("producto", "articulo", "product"),
    ("existencias", "stock", "inventario", "inventory"),
    ("caja", "arqueo", "cajon", "till", "drawer", "cash"),
    ("mesa", "table"),
    ("reserva", "reservation", "booking"),
    ("cita", "appointment"),
    ("factura", "invoice"),
    ("pago", "pagar", "payment", "pay"),
    ("negocio", "empresa", "business", "company"),
    ("plan", "suscripcion", "subscription"),
    ("sesion", "session"),
    ("app", "aplicacion", "modulo", "module"),
    ("precio", "tarifa", "price"),
    ("iva", "impuesto", "tax", "vat"),
    ("categoria", "familia", "category"),
    ("descuento", "discount"),
    ("proveedor", "supplier"),
    ("comanda", "pedido", "order"),
    ("cocina", "kitchen"),
    ("turno", "horario", "shift", "schedule"),
    ("rol", "role"),
    ("direccion", "address"),
    ("nombre", "name"),
    ("clave", "key"),
    ("telefono", "movil", "phone"),
    ("foto", "imagen", "photo", "image", "picture"),
    ("impresora", "imprimir", "printer", "print"),
    ("bono", "voucher"),
    ("menu", "combo"),
    ("ticket", "tique", "recibo", "receipt"),
    ("aviso", "alerta", "notificacion", "alert", "notice", "notification"),
    ("grupo", "group"),
    ("compra", "purchase"),
    ("dato", "datos", "data"),
    ("descarga", "descargar", "download"),
    ("ficha", "card"),
    ("nota", "note"),
    ("dispositivo", "aparato", "tablet", "portatil", "ordenador", "device", "laptop", "computer"),
    ("carpeta", "folder"),
    ("perfil", "profile"),
    ("avatar", "foto de perfil", "profile picture", "profile photo"),
    ("recibir", "receive"),
    ("devolucion", "reembolso", "refund"),
    ("aparcar", "aparcada", "park"),
    ("etiqueta", "tag"),
    ("ajustes", "ajuste", "configuracion", "configurar", "configura", "settings", "setting", "setup", "configure",
     "set up"),
)
_WORD = re.compile(r"[a-z0-9]+")
#: What ends a sentence or a quote: its first word may be a command («Ficha la entrada»), a question word, a name.
_BREAK = re.compile(r"[«»\"“”()\[\].,;:!?¿¡\n]+")
#: Words kept whole: cut, they would be another word's stem («personal», the staff, is not «persona»).
_WHOLE = frozenset({"personal"})
#: Words kept apart from another's stem (as said, or without their plural «s»): «tablet» is no «table», «compartido»
#: no «company», «peluquería» (the business) no «peluquero» (its staff), «carta» (the menu) no «cart», «contrato» and
#: «contraseña» no «control», «recibo» (a receipt) no «recibir», «ficha» (a customer's card) no «fichar»,
#: «settings» no «set», «registro» (a record) no «register» (the till).
_APART_WORDS = {"ficha": "ficha", "carta": "carta", "recibo": "recibo", "registro": "registro", "fiche": "fichar",
                "ficho": "fichar"}
_APART_PREFIXES = (
    ("peluqueri", "peluqueri"), ("contrasen", "contrasen"), ("compart", "compart"), ("contract", "contrat"),
    ("contrat", "contrat"), ("receipt", "receipt"), ("fichaj", "fichar"), ("fichar", "fichar"), ("fichad", "fichar"),
    ("fichand", "fichar"), ("ficham", "fichar"), ("fichal", "fichar"), ("tablet", "tablet"), ("setting", "setting"),
)
#: A noun that is a command at the start of a sentence, followed by these: «ficha la entrada de Ana» clocks in, «abre
#: la ficha de Ana» is her card; «reserva una mesa» books, «cancela la reserva» names one.
_COMMANDS = {
    "ficha": ("fichar", frozenset({"a", "al", "la", "el", "mi", "su", "tu", "ya", "entrada", "salida", "ahora"})),
    "reserva": ("reservar", frozenset({"una", "un", "mesa", "para", "a", "al", "hoy", "manana"})),
}
#: Endings of a Spanish verb that end in «s» («vendimos»): cut before a plural «s» is.
_VERB_S_ENDINGS = ("amos", "emos", "imos")
#: Endings cut once a plural «s» is, longest first: Spanish and English tenses, participles and gender.
_ENDINGS = ("ieron", "iendo", "ando", "aron", "aste", "iste", "ado", "ido", "ada", "ida", "aba", "ing", "ar", "er",
            "ir", "ed", "a", "e", "i", "o")
#: English endings before which a verb doubles its last consonant («tagged», «stopping»; never «billing»).
_DOUBLING = frozenset({"ed", "ing"})
#: The verbs said in two words or more, and what only asks («give me», «tell me»): their words name nothing.
_FILLERS = ("give me", "give us", "tell me", "tell us", "let me know")
_PHRASES = tuple(sorted({form for forms in VERBS.values() for form in forms if " " in form} | set(_FILLERS)))
#: Each verb said in one word → the actions it asks for.
_VERB_OF: dict[str, frozenset[str]] = {}
for _verb, _forms in VERBS.items():
    for _form in _forms:
        if " " not in _form:
            _VERB_OF[_form] = _VERB_OF.get(_form, frozenset()) | {_verb}
#: The words a verb is said with: their stem keeps a root of three letters («sube», «subir» → «sub»).
_VERB_WORDS = frozenset(_VERB_OF) - _NOT_VERBS | _OTHER_VERBS


def _plain(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


def _unclitic(word: str) -> str | None:
    """The command ``word`` without the pronouns at its end («cobrale» → «cobra», «dime» → «di»), when what is left is
    a verb and the word is not another (``_NOT_COMMANDS``: «iniciales»); else ``None``."""
    if word in _NOT_COMMANDS:
        return None
    for clitic in _ENCLITICS:
        if word.endswith(clitic) and len(word) > len(clitic):
            rest = word[: -len(clitic)]
            if rest in _VERB_WORDS or rest in _IRREGULAR:
                return rest
    return None


def _apart(word: str) -> str | None:
    if word in _APART_WORDS:
        return _APART_WORDS[word]
    return next((kept for prefix, kept in _APART_PREFIXES if word.startswith(prefix)), None)


@lru_cache(maxsize=65_536)
def stem(word: str) -> str:
    """``word`` (plain: lowercase, no accents) cut to its stem, Spanish or English: the pronouns of a command off
    («cóbrale» is «cobra»), a plural «s» and one ending of a verb or a gender off, then five letters at most («vendí»,
    «vendido», «vendimos» → «vend»; «clientes», «client» → «clien»). The root keeps four letters, three for a plural
    («apps» → «app»; «mesa» is never «mes») and for a verb («sube», «subir» → «sub»); an English verb's doubled
    consonant goes with its ending («tagged» → «tag»); a word of ``_WHOLE`` stays whole and one kept apart
    (``_APART_WORDS``, ``_APART_PREFIXES``) has its own stem."""
    if word in _WHOLE:
        return word
    bare = _unclitic(word)
    verbal = bare is not None or word in _VERB_WORDS
    word = bare or word
    if word in _IRREGULAR:
        return _IRREGULAR[word]
    if (kept := _apart(word)) is not None:
        return kept
    for ending in _VERB_S_ENDINGS:
        if word.endswith(ending) and len(word) - len(ending) >= 4:
            return word[: -len(ending)][:5]
    if word.endswith("s") and len(word) >= 4:
        word = word[:-1]
        if (kept := _apart(word)) is not None:
            return kept
    root = 3 if verbal else 4
    for ending in _ENDINGS:
        if word.endswith(ending) and len(word) - len(ending) >= root:
            word = word[: -len(ending)]
            if ending in _DOUBLING and word[-1] == word[-2] and word[-1] not in "aeioulsfz":
                word = word[:-1]
            break
    return word[:5]


def _sentences(text: str) -> list[list[str]]:
    """The plain words of ``text``, by sentence or quote (``_BREAK``), a noun at the start that is a command
    (``_COMMANDS``) said as its verb."""
    found = []
    for part in _BREAK.split(text):
        words = _WORD.findall(_plain(part))
        if words and words[0] in _COMMANDS:
            verb, before = _COMMANDS[words[0]]
            if len(words) > 1 and words[1] in before:
                words[0] = verb
        if words:
            found.append(words)
    return found


def stems(text: str) -> set[str]:
    """The words of ``text`` that may name something, as their stems (``stem``): without accents, lowercase, of three
    letters or more and none that names nothing by itself (``STOP_WORDS``)."""
    return {
        stem(word) for words in _sentences(text) for word in words if len(word) >= 3 and word not in STOP_WORDS
    }


@lru_cache(maxsize=16_384)
def _stems_of(text: str) -> frozenset[str]:
    return frozenset(stems(text))


@lru_cache(maxsize=4_096)
def _taken(schema: type) -> frozenset[str]:
    """The stems of the data an operation's input ``schema`` takes, by their names (``price``, ``party_size``)."""
    return frozenset(stems(" ".join(name.replace("_", " ") for name in getattr(schema, "model_fields", {}))))


def _groups(synonyms: Iterable[Iterable[str]]) -> tuple[tuple[str, ...], ...]:
    return tuple(tuple(group) for group in synonyms)


@lru_cache(maxsize=64)
def _synonyms(extra: tuple[tuple[str, ...], ...] = ()) -> tuple[dict[str, frozenset[str]], tuple]:
    """Each stem of ``SYNONYMS`` and of the project's ``extra`` groups → the stems of every group it is in; and each
    phrase of them → the stems of its group's words."""
    index: dict[str, set[str]] = {}
    phrases: list[tuple[str, frozenset[str]]] = []
    for group in (*SYNONYMS, *extra):
        said = {stem(_plain(word)) for word in group if " " not in word}
        for one in said:
            index.setdefault(one, set()).update(said)
        phrases += [(f" {' '.join(_WORD.findall(_plain(word)))} ", frozenset(said)) for word in group if " " in word]
    return {one: frozenset(group) for one, group in index.items()}, tuple(phrases)


@lru_cache(maxsize=65_536)
def _concept(word: str, extra: tuple[tuple[str, ...], ...] = ()) -> frozenset[str]:
    """What the plain ``word`` names: its stem and those of its synonyms (``SYNONYMS`` and the project's ``extra``)."""
    one = stem(word)
    return _synonyms(extra)[0].get(one, frozenset()) | {one}


class Asked(NamedTuple):
    """What texts ask (``asked``): what their words name (``concepts``, each a set of stems), the actions they ask for
    (``verbs``), whether they ask to know (``reading``), what a question asks about (``about``: what the action it names
    without asking for it names, «pay» in «what can customers pay with?»), whether it asks how something is done
    (``howto``) and what each command acts on (``objects``: the first thing it names from its verb on — «crea la
    carpeta Facturas» creates a folder; «cobra la mesa» charges a sale, the verb's own thing), of which ``records``
    the ones a word after the verb names («borra el cliente Ana»: a customer to find)."""

    concepts: frozenset[frozenset[str]]
    verbs: frozenset[str]
    reading: bool
    about: frozenset[frozenset[str]]
    howto: bool
    objects: frozenset[frozenset[str]] = frozenset()
    records: frozenset[frozenset[str]] = frozenset()


def _phrase_verbs(phrase: str) -> frozenset[str]:
    """The actions a verb said in words (`` set up ``) asks for."""
    return frozenset(verb for verb, forms in VERBS.items() if phrase.strip() in forms)


def _verbs_of(word: str) -> frozenset[str]:
    """The actions the plain ``word`` asks for: as said, or without the pronouns of a command («cóbrale»)."""
    found = _VERB_OF.get(word)
    if found is None and (bare := _unclitic(word)) is not None:
        found = _VERB_OF.get(bare)
    return found or frozenset()


def _opening(words: list[str]) -> tuple[list[str], bool]:
    """A sentence from the first word that says something — greetings (``_GREETINGS``) and the words of a request
    (``_REQUESTS``: «puedes», «can you») off — and whether it is a request."""
    at, request = 0, False
    while at < len(words):
        if words[at] in _GREETINGS:
            at += 1
            continue
        said = next((len(one) for one in (tuple(words[at : at + 2]), (words[at],)) if one in _REQUESTS), 0)
        if not said:
            break
        at, request = at + said, True
    return words[at:], request


def _commands(words: list[str]) -> bool:
    """Whether a sentence (``_opening``) is a command: it starts with a verb that does something («cobra la mesa 4»,
    «delete customer Ana»), or with «do» and what it does («do a refund»)."""
    if not words:
        return False
    if words[0] == "do":
        words = [word for word in words[1:3] if word not in _ARTICLES][:1]
    return bool(words) and bool(_verbs_of(words[0]) - READ_VERBS)


def _how_to(sentences: list[list[str]]) -> str | None:
    """Whether a sentence asks how something is done (``_HOW_TO``), after the words that only ask for it («dime cómo…»):
    the word that says what is done after «cómo» («invito»), «-» when none; ``None`` when no sentence asks so."""
    for said in sentences:
        lead = 0
        while lead < min(len(said), 3) and said[lead] in _HOW_TO_LEADS | _GREETINGS:
            lead += 1
        words = said[lead:]
        if not words:
            continue
        after = [word for word in words[1:] if word not in _CLITICS]
        if words[0] in _HOW_TO and after:
            if after[0] in _HOW_TO[words[0]]:
                return "-"
            if words[0] == "como" and after[0].endswith("o") and len(after[0]) >= 4:
                return after[0]
    return None


def _is_question(text: str, sentences: list[list[str]]) -> bool:
    """Whether ``text`` is a question: never when a sentence is a command (``_commands``, after its greetings and the
    words of a request: «hola, ¿puedes cobrar la mesa 4?», «cobra la mesa 4 y dime cuánto es», «do a refund»); else a
    question word with its accent, a text that starts with one or with the auxiliary of a yes/no question, or its
    marks («?», «¿»). An unaccented «que» asks only with the marks: inside a sentence («dice que sí»), after a command
    («anula el ticket, que me equivoqué») or at the start of a wish («que no se pueda cobrar sin cliente») it is
    none."""
    if any(_commands(_opening(words)[0]) for words in sentences):
        return False
    if _INTERROGATIVE.search(unicodedata.normalize("NFC", text).lower()):
        return True
    marked = "?" in text or "¿" in text
    first = sentences[0][0] if sentences else ""
    return first in _AUXILIARIES or (first in QUESTION_WORDS and first != "que") or marked


def _objects(
    sentences: list[list[str]], acting: Mapping[str, frozenset[str]], verbal: Collection[str], extra: tuple
) -> tuple[set[frozenset[str]], set[frozenset[str]]]:
    """What the command of each sentence acts on: the first thing named from its verb on — the verb's own when it
    names one («cobra»: a sale), else the first word after it that names something («crea la carpeta»: a folder) —;
    and of those, the ones named by a word after the verb (a record to find)."""
    found: set[frozenset[str]] = set()
    after: set[frozenset[str]] = set()
    for words in sentences:
        seen = False
        for word in words:
            if word in acting or word in verbal:
                own = _concept(word, extra) if word in acting and not seen else frozenset()
                if len(own) > 1:
                    found.add(own)
                    break
                seen = True
            elif seen and len(word) >= 3 and word not in STOP_WORDS:
                found.add(_concept(word, extra))
                after.add(_concept(word, extra))
                break
    return found, after


def asked(texts: Iterable[str], synonyms: Iterable[Iterable[str]] = ()) -> Asked:
    """What ``texts`` ask (``Asked``): what each of their words names (``_concept``, with the project's ``synonyms``; a
    word of a verb's phrase names nothing, nor a verb but by its synonyms: «show me», «dame»), the actions they ask for
    (``VERBS``, a command with its pronouns too) and whether they ask to know (a question, ``_is_question``, or a read
    of ``READ_VERBS``). A question asks to do nothing it names unless it is a request («can you…?») or asks how («how
    do I…?»): its other actions are what it asks about (``Asked.about``)."""
    extra = _groups(synonyms)
    phrases_named = _synonyms(extra)[1]
    concepts: set[frozenset[str]] = set()
    verbs: set[str] = set()
    about: set[frozenset[str]] = set()
    objects: set[frozenset[str]] = set()
    records: set[frozenset[str]] = set()
    reading = howto = False
    for text in texts:
        sentences = _sentences(text)
        joined = [f" {' '.join(words)} " for words in sentences]
        found = {phrase for phrase in _PHRASES if any(f" {phrase} " in one for one in joined)}
        verbal = {word for phrase in found for word in phrase.split()}
        said = {verb for verb, forms in VERBS.items() if not found.isdisjoint(forms)}
        acting: dict[str, frozenset[str]] = {}
        for words in sentences:
            for word in words:
                if word not in verbal and (of := _verbs_of(word)):
                    acting[word] = of
        doing = _how_to(sentences)
        if doing and doing != "-" and doing not in acting:
            acting[doing] = _verbs_of(doing[:-1] + "a") or _verbs_of(doing[:-1] + "e")
        for of in acting.values():
            said |= of
        # A word that asks (a verb) names a thing only through its synonyms («cobra»: a sale); «show», «dame» none.
        naming = [
            word for words in sentences for word in words
            if (word not in verbal or word in _PHRASE_NAMES) and len(word) >= 3 and word not in STOP_WORDS
            and (word not in acting or len(_concept(word, extra)) > 1)
        ]
        concepts |= {_concept(word, extra) for word in naming}
        concepts |= {group for phrase, group in phrases_named if any(phrase in one for one in joined)}
        acted, named_after = _objects(sentences, acting, verbal, extra)
        objects |= acted
        records |= named_after
        question = _is_question(text, sentences) and not any(_opening(words)[1] for words in sentences)
        if question and not doing:
            asked_about = said - READ_VERBS
            about |= {_concept(word, extra) for word, of in acting.items() if of & asked_about}
            about |= {
                group
                for phrase, group in phrases_named
                if phrase.strip() in found and _phrase_verbs(phrase) & asked_about
            }
            said -= asked_about
        reading = reading or question or not said.isdisjoint(READ_VERBS)
        howto = howto or doing is not None
        verbs |= said
    return Asked(
        frozenset(concepts), frozenset(verbs), reading, frozenset(about), howto, frozenset(objects), frozenset(records)
    )


@cache
def app_words(label: str, language: str) -> frozenset[str]:
    """How a person names the app ``label``: its id, its name and its menu, in English and in ``language``."""
    config = config_of(label)
    words = stems(label.replace("_", " "))
    if config is None:
        return frozenset(words)
    for lang in ("en", language):
        with translation.override(lang):
            words |= stems(str(config.verbose_name))
            for nav in getattr(config, "navigation", []) or []:
                words |= stems(str(nav.label))
    return frozenset(words)


#: The stems of an operation's entity that name an app («base.app.enable»): an app named by its name is that entity.
_APP_THING = frozenset(stem(word) for word in ("app", "aplicacion", "modulo", "module"))


#: The words of an action that say for what, not what it acts on (``list_for_customer``, ``by_phone``,
#: ``create_from_sale``): what comes after them is no object of it.
_QUALIFIERS = frozenset({"for", "by", "from", "to", "of", "in", "with"})


@lru_cache(maxsize=4_096)
def _acts(op: Operation) -> frozenset[str]:
    """The words of ``op``'s action (``create_folder`` → «create», «folder»)."""
    return frozenset(op.name.split(".")[2].split("_"))


@lru_cache(maxsize=4_096)
def _things(op: Operation) -> frozenset[str]:
    """The stems of what ``op`` is of: its entity and what its action acts on (``_parts``)."""
    _, entity, action = op.name.split(".")
    return _stems_of(entity.replace("_", " ")) | _parts(action)[0]


@lru_cache(maxsize=8_192)
def _parts(action: str) -> tuple[frozenset[str], frozenset[str], frozenset[str]]:
    """The stems of what an operation's ``action`` acts on — its words before a qualifier (``_QUALIFIERS``) that are no
    action asked (``create_folder`` → «folder», ``avatar_set`` → «avatar», ``today``) —, of the actions it does
    (``create``) and of what it says for what (``customer`` of ``list_for_customer``)."""
    words = action.split("_")
    cut = next((i for i, word in enumerate(words) if word in _QUALIFIERS), len(words))
    acted_on = [word for word in words[:cut] if word not in VERBS]
    doing = [word for word in words[:cut] if word in VERBS]
    return _stems_of(" ".join(acted_on)), _stems_of(" ".join(doing)), _stems_of(" ".join(words[cut:]))


def relevant(
    tools: dict[str, Operation],
    texts: Iterable[str],
    language: str,
    *,
    always: Iterable[str] = (),
    app_words: Callable[[str, str], frozenset[str]] = app_words,
    synonyms: Iterable[Iterable[str]] = (),
    howto: Iterable[str] = (),
) -> list[Operation]:
    """The tools of what ``texts`` ask, best first, at most ``MAX_TOOLS``; ``always`` (what is always at hand) first.

    Each thing the question names (``asked``, with the project's ``synonyms``) counts 2 when it names the tool's entity
    or what its action acts on (``_parts``: ``create_folder`` acts on a folder), else 1 when it names only the tool's
    app (in either language, ``app_words``: an app's name breaks ties, it never drowns the thing asked) — unless the
    question names no tool's thing at all: then the app named by its own name is the thing of its tools («la cocina»:
    its tickets and stations; «abre la caja»: the till's session); 2 more when it
    names the action itself, 1 when it names what the action says it is for (``list_for_customer``), and 1 for each of
    its description, what people say to ask for it (``asks_of``, in any language) and the data its input takes.

    The action asked (``VERBS``) of a thing the question names adds 9, 1 more when the tool's action is that verb
    itself (``create``, before ``bulk_create``) and 3 more when that thing is what the command acts on
    (``Asked.objects``: «crea la carpeta Facturas» creates a folder, not an invoice); «activa la app» is
    ``base.app.enable``, never an operation of the app named after it, and so is «activa los clientes», an app named
    by its name. Of no thing named, it adds 7 to a write that takes a datum the question names («cambia el precio»: a
    write that takes a ``price``; «turn off the alerts»: a write that takes them, as turning on or off changes it), 3 to
    any other write unless a tool does that to what the command acts on, or it is an app named by its name («reserva
    una mesa»: no write of the staff; «abre la cocina»: no other app's open), 1 to
    a read of the app named and nothing to any other read: «¿cuántos…?» is no list of everything, and what a read is
    filtered by is not what it reads.

    A write of a thing named after its verb brings its reads 3 («borra el cliente Ana»: the read that finds Ana). A
    question that asks to know and to do nothing puts the reads first (1), a thing's list before its other reads (1),
    and the reads of what it asks about 3 more («what can customers pay with?»: the payment methods); a how-to question
    gives the help (``howto``, the project's documentation search) ``HOWTO_POINTS``. Ties go by name: the same
    question, the same tools."""
    return _relevant(tools, texts, language, always=always, app_words=app_words, synonyms=synonyms, howto=howto)


def _relevant(
    tools: dict[str, Operation],
    texts: Iterable[str],
    language: str,
    *,
    always: Iterable[str] = (),
    app_words: Callable[[str, str], frozenset[str]] = app_words,
    synonyms: Iterable[Iterable[str]] = (),
    howto: Iterable[str] = (),
    asks: Callable[[Operation], frozenset[str]] | None = None,
) -> list[Operation]:
    """``relevant``, with what each tool's asks say read by ``asks`` (the QA leaves out the phrase it ranks)."""
    said = asked(texts, synonyms)
    concepts, verbs, about = said.concepts, said.verbs, said.about
    asks = asks or _asks_stems
    writing = bool(verbs - READ_VERBS)
    switching = not verbs.isdisjoint(SWITCHES)
    helps = frozenset(howto) if said.howto else frozenset()
    always = tuple(always)

    def named(words: frozenset[str]) -> int:
        return sum(1 for concept in concepts if not concept.isdisjoint(words))

    # The things the catalogue's tools are of. A question that names none of them but an app by its name («la cocina»:
    # the kitchen app, of tickets and stations) makes that app the thing; beside a thing named («el registro de
    # eventos») the app's name only breaks ties.
    things = frozenset().union(*(_things(op) for op in tools.values())) if concepts else frozenset()
    every_app = {op.app_label for op in tools.values()} if concepts else set()
    names_a_thing = any(not concept.isdisjoint(things) for concept in concepts)
    by_app = set() if names_a_thing else {
        concept for concept in concepts if any(not concept.isdisjoint(app_words(label, language)) for label in every_app)
    }
    apps_named = switching and any(named(app_words(label, language)) for label in every_app)
    # What a command acts on, when a tool does that to it or it is an app named by its name: then the writes of other
    # things are not what it asks («reserva una mesa» is no staff's create; «create a 10% discount» has no tool that
    # creates a discount, so the creates stay).
    aimed_at = writing and any(
        concept in by_app
        or any(
            not concept.isdisjoint(_things(op)) and not verbs.isdisjoint(_acts(op))
            for op in tools.values()
        )
        for concept in said.objects
    )

    def score(op: Operation) -> int:
        app, entity, action = op.name.split(".")
        named_app, named_entity = app_words(app, language), _stems_of(entity.replace("_", " "))
        acted_on, doing, qualified = _parts(action)
        places = thing = 0
        aimed = found = app_named = False
        for concept in concepts:
            in_app = not concept.isdisjoint(named_app)
            is_thing = (
                not concept.isdisjoint(named_entity)
                or not concept.isdisjoint(acted_on)
                or (in_app and concept in by_app)
            )
            thing += is_thing
            aimed = aimed or (is_thing and concept in said.objects)
            found = found or (is_thing and concept in said.records)
            app_named = app_named or in_app
            places += 2 if is_thing else in_app
            places += 2 * (not concept.isdisjoint(doing)) + (not concept.isdisjoint(qualified))
        if not thing and apps_named and not _APP_THING.isdisjoint(named_entity):
            thing = 1
        takes = named(_taken(op.input))
        points = places + named(_stems_of(description(op))) + named(asks(op)) + takes
        acts = action.split("_")
        matched = verbs.intersection(acts)
        if matched:
            if thing:
                points += 9 + (action in verbs) + 3 * aimed
            else:
                writes = matched - READ_VERBS
                points += 7 if takes and writes else 3 if writes and not aimed_at else 1 if app_named else 0
        elif switching and takes and not _CHANGES.isdisjoint(acts):
            points += 7
        if op.kind == "query":
            if about and any(not concept.isdisjoint(named_entity) for concept in about):
                points += 3
            if writing and found:
                points += 3
            if said.reading and not writing:
                points += 1 + (action == "list" and thing > 0)
        if op.name in helps:
            points += HOWTO_POINTS
        return points

    first = [tools[name] for name in always if name in tools]
    ranked = sorted((op for op in tools.values() if op.name not in always), key=lambda op: (-score(op), op.name))
    return [*first, *ranked][:MAX_TOOLS]


@lru_cache(maxsize=4_096)
def _asks_stems(op: Operation) -> frozenset[str]:
    """The stems of every phrase of ``op``'s asks, in every language: read once per operation (by identity; its
    ``ai=`` does not change once declared), however many turns rank it — the QA ranks once per ask of hundreds."""
    return _stems_of(" ".join(phrase for phrases in asks_of(op).values() for phrase in phrases))


@cache
def input_schema(op: Operation) -> dict:
    return op.input.model_json_schema()


@cache
def output_schema(op: Operation) -> dict:
    return op.output.model_json_schema()


def tool_spec(op: Operation) -> dict:
    """``op`` as the gateway takes a tool (OpenAI's ``function``)."""
    return {"type": "function", "name": tool_name(op.name), "description": description(op), "parameters": input_schema(op)}


def config_of(label: str) -> LiveAppConfig | None:
    return next((config for config in all_live_app_configs() if config.label == label), None)


# ── The card of a write ──────────────────────────────────────────────────────────────────────────────────────────


def resolved(prop: dict, defs: dict) -> dict:
    """``prop`` with the first branch of its union that is not ``null`` and the schema its ``$ref`` names."""
    for branch in prop.get("anyOf", []):
        if branch.get("type") != "null":
            return resolved({**branch, **{k: v for k, v in prop.items() if k != "anyOf"}}, defs)
    ref = prop.get("$ref")
    return {**defs.get(ref.rsplit("/", 1)[-1], {}), **prop} if ref else prop


#: The mark of an amount (``json_schema_extra={"money": True}``, on a whole number): in the minor unit of the currency
#: it is in — 1250 is 12.50 €, ¥1,250 has no cents. The card paints it as money and the model is told so by its tool,
#: whatever its description says: the words are for the model, the mark is the platform's.
MONEY = "money"


def is_money(name: str, prop: dict) -> bool:
    """Whether the datum ``name`` is an amount: its schema's mark (``MONEY``). A name in ``_cents`` still counts while
    some schemas give one without its mark; a description's words never do."""
    return prop.get(MONEY) is True or name.endswith("_cents")


def is_signed(prop: dict) -> bool:
    """Whether the schema declares the datum signed (``json_schema_extra={"signed": True}``): an amount (``MONEY``) that
    says over or short, as a cash count's difference, which the card writes with its sign («+» over)."""
    return prop.get("signed") is True


def sends_amount(value: Any, prop: dict, defs: dict, name: str, depth: int = 0) -> bool:
    """Whether ``value`` carries an amount (``MONEY``) as its schema ``prop`` declares it, at any depth."""
    prop = fitting(value, prop, defs)
    if depth > 8:  # a schema that names itself
        return False
    if isinstance(value, int) and not isinstance(value, bool):
        return is_money(name, prop)
    if isinstance(value, dict):
        props = prop.get("properties", {})
        return any(sends_amount(inner, props.get(key, {}), defs, key, depth + 1) for key, inner in value.items())
    if isinstance(value, list):
        items = prop.get("items")
        items = items if isinstance(items, dict) else {}
        return any(sends_amount(item, items, defs, name, depth + 1) for item in value)
    return False


def generated_title(name: str) -> str:
    """The title pydantic makes up for a field without one (``closing_balance`` → «Closing Balance»)."""
    return name.title().replace("_", " ").strip()


def _in_code_language() -> bool:
    """Whether the active language is the one the code's texts are written in (and fall back to): English."""
    return (translation.get_language() or settings.LANGUAGE_CODE).split("-")[0] == settings.LANGUAGE_CODE.split("-")[0]


@cache
def model_fields(app_label: str, entity: str, name: str) -> tuple:
    """The fields ``name`` of the models of the app ``app_label``, the model of the operation's ``entity`` first —
    another may mean something else by it. Their metadata only: no query."""
    config = config_of(app_label)
    if config is None:
        return ()
    own = entity.replace("_", "")
    found = []
    for model in sorted(config.get_models(), key=lambda model: not model._meta.model_name.endswith(own)):
        try:
            found.append(model._meta.get_field(name))
        except FieldDoesNotExist:
            continue
    return tuple(found)


def verbose_name(app_label: str, entity: str, name: str) -> Any:
    """The name the models of the app ``app_label`` give their field ``name`` (lazy: said in the active language), or
    ``None``."""
    named_ = (getattr(field, "verbose_name", None) for field in model_fields(app_label, entity, name))
    return next((verbose for verbose in named_ if verbose), None)


def choice_label(app_label: str, entity: str, name: str, value: Any) -> Any:
    """The label the models of the app ``app_label`` give the value ``value`` of their field ``name`` — its
    ``choices``, the ones its screens show (lazy: said in the active language) —, or ``None``."""
    for field_ in model_fields(app_label, entity, name):
        labels = dict(getattr(field_, "flatchoices", None) or ())
        if value in labels:
            return labels[value]
    return None


def own_title(name: str, title: str | None) -> str | None:
    """The title the schema gives the datum ``name`` itself — not the one pydantic makes up from its name —, in the
    active language: as a catalog translates it, or as written when the person reads the code's language; else
    ``None`` (one nobody translated never reaches a Spanish card)."""
    if title and title != generated_title(name):
        translated = gettext(title)
        if translated != title or _in_code_language():
            return translated
    return None


def label(op: Operation, name: str, title: str | None) -> str:
    """How the card names the datum ``name``, in the active language and never by a technical name: by the title its
    schema gives it (``own_title``); else by the name its app's models give that field, the one its screens show; else
    by its title, through the catalogs. One way for every app: nothing to list here by hand."""
    own = own_title(name, title)
    if own is not None:
        return own
    verbose = verbose_name(op.app_label, op.name.split(".")[1], name)
    if verbose is not None:
        return capfirst(str(verbose))
    return gettext(title or generated_title(name))


#: What a card shows of a secret instead of its value: the same in every language.
HIDDEN = "••••••••"


def _is_secret(prop: dict) -> bool:
    """Whether the schema declares the datum secret: a password, a certificate, a key (pydantic's ``SecretStr``:
    ``format: password``, ``writeOnly``)."""
    return prop.get("format") == "password" or prop.get("writeOnly") is True


def hidden(value: Any, prop: dict, defs: dict) -> Any:
    """``value`` with each secret its schema ``prop`` declares, at any depth, as ``HIDDEN``; an empty one hides
    nothing. A card never carries a secret as typed: neither on the screen nor in what the browser receives."""
    if value is None or value == "":
        return value
    ref = prop.get("$ref")
    if ref:
        prop = {**defs.get(ref.rsplit("/", 1)[-1], {}), **{key: inner for key, inner in prop.items() if key != "$ref"}}
    if _is_secret(prop):
        return HIDDEN
    # Each branch of a union hides its own: what any of them declares secret is hidden.
    for branch in [*prop.get("anyOf", []), *prop.get("oneOf", []), *prop.get("allOf", [])]:
        value = hidden(value, branch, defs)
    if isinstance(value, dict):
        props = prop.get("properties", {})
        extra = prop.get("additionalProperties")
        extra = extra if isinstance(extra, dict) else {}
        return {key: hidden(inner, props.get(key, extra), defs) for key, inner in value.items()}
    if isinstance(value, list):
        items, prefix = prop.get("items"), prop.get("prefixItems", [])
        items = items if isinstance(items, dict) else {}
        return [hidden(item, prefix[i] if i < len(prefix) else items, defs) for i, item in enumerate(value)]
    return value


#: The mark of a datum that names a record (``json_schema_extra={"refers": {"read": "<a query>", "by": "<its input>",
#: "name": "<the datum of its answer that names it>"}}``): the project's words name it (``Words.reference``). A datum
#: the schema says is an id (``format: uuid``) is a record too: a card never shows it by its id.
REFERS = "refers"

#: The moments a schema declares (``format``), said as the person's language writes them (``Words.moment``).
MOMENTS = ("date-time", "date", "time")

#: The mark of a key of the caller's attempt (``json_schema_extra={"attempt_key": True}``, on a text): an idempotency
#: key, born once and the same on every retry so a retry never charges, sends or prints twice. Nobody can judge it:
#: the card and its preview leave it out, at any depth; the write gets it as sent.
ATTEMPT_KEY = "attempt_key"


def is_attempt_key(prop: dict) -> bool:
    return prop.get(ATTEMPT_KEY) is True


def refers_of(prop: dict) -> dict | None:
    """The read the schema ``prop`` marks to name its record (``REFERS``), or ``None``."""
    declared = prop.get(REFERS)
    return declared if isinstance(declared, dict) else None


def is_uuid(value: Any) -> bool:
    """Whether ``value`` is an id as a schema's ``format: uuid`` takes it."""
    try:
        uuid.UUID(value)
    except (TypeError, ValueError, AttributeError):
        return False
    return True


#: What a card leaves out: a record it cannot name, an attempt key.
LEFT_OUT = object()

#: The mark of a datum of a card that is a list whose every item ``said`` put in words — a record by its name (or left
#: out, none), a moment, a value of a closed list by its label, an amount —, never one as sent: the screen says its items
#: one after another. A list without it (texts sent as they are, codes nobody names, lines) says how many it carries.
NAMED = "named"


class Words(Protocol):
    """How a project says a card's data in words, for the person (``language``) and the write (``op``) of the card.

    ``within`` gives the words of the data of an object it sends (the Hub: in the currency that object names);
    ``money`` the currency of the card's top-level amounts as its screen takes it (``{"currency", "decimals"}``, or
    ``None`` for the project's own); ``amount`` an amount nested in an object or a list; ``priced`` false when the
    amounts are to go as sent (a currency that is none); ``moment`` a moment (``MOMENTS``) or ``None`` when it is
    none; ``reference`` the name of the record a datum names, or ``LEFT_OUT``; ``app_name`` where the write happens,
    as the person knows it."""

    op: Operation
    language: str
    priced: bool

    def within(self, value: Any, props: dict, defs: dict) -> Words: ...

    def money(self) -> dict | None: ...

    def amount(self, value: int) -> Any: ...

    def moment(self, value: str, kind: str) -> str | None: ...

    def reference(self, value: Any, prop: dict) -> Any: ...

    def app_name(self) -> str: ...


@dataclass(frozen=True)
class PlainWords:
    """Words that read nothing: amounts in ``currency`` with ``decimals`` (euros with two by default), a moment at UTC as
    Django's formats of the active language write it, a record left out (no read to name it) and the app by its
    name."""

    op: Operation
    language: str
    currency: str = "EUR"
    decimals: int = 2
    priced: bool = True

    def within(self, value: Any, props: dict, defs: dict) -> PlainWords:
        return self

    def money(self) -> dict | None:
        return {"currency": self.currency, "decimals": self.decimals}

    def amount(self, value: int) -> Any:
        return {"kind": "money", "value": value, "money": self.money()}

    def moment(self, value: str, kind: str) -> str | None:
        try:
            if kind == "date":
                return formats.date_format(dt.date.fromisoformat(value), "DATE_FORMAT")
            if kind == "time":
                return formats.time_format(dt.time.fromisoformat(value).replace(tzinfo=None), "TIME_FORMAT")
            moment = dt.datetime.fromisoformat(value)
        except ValueError:
            return None
        if moment.tzinfo is not None:
            moment = moment.astimezone(dt.UTC).replace(tzinfo=None)
        return formats.date_format(moment, "DATETIME_FORMAT")

    def reference(self, value: Any, prop: dict) -> Any:
        return LEFT_OUT

    def app_name(self) -> str:
        config = config_of(self.op.app_label)
        return str(config.verbose_name) if config is not None else self.op.app_label

    @classmethod
    def of_answer(cls, read: Operation, ctx: OperationContext, answer: dict) -> PlainWords:
        """The words of a preview's read: in the currency it answers (``currency``, ``currency_decimals``), else euros."""
        currency = answer.get("currency")
        decimals = answer.get("currency_decimals")
        return cls(
            read,
            ctx.language,
            currency if isinstance(currency, str) and currency else cls.currency,
            decimals if isinstance(decimals, int) and not isinstance(decimals, bool) else cls.decimals,
        )


#: The type of a value each JSON Schema type names.
_TYPES = {"object": dict, "array": list, "string": str, "integer": int, "number": int | float, "boolean": bool}


def _fits(value: Any, branch: dict) -> bool:
    """Whether ``value`` has the shape of ``branch``: its type and, an object, no key it does not take and its
    constants (a discriminator, as an automation's trigger ``kind``)."""
    expected = _TYPES.get(branch.get("type", ""))
    if expected is not None and not isinstance(value, expected):
        return False
    if not isinstance(value, dict):
        return True
    props = branch.get("properties", {})
    if branch.get("additionalProperties") is False and not set(value) <= set(props):
        return False
    return all(value[key] == inner["const"] for key, inner in props.items() if key in value and "const" in inner)


def _referred(prop: dict, defs: dict) -> dict:
    """``prop`` with the schema its ``$ref`` names, what it says itself on top."""
    ref = prop.get("$ref")
    if not ref:
        return prop
    return {**defs.get(ref.rsplit("/", 1)[-1], {}), **{key: inner for key, inner in prop.items() if key != "$ref"}}


def fitting(value: Any, prop: dict, defs: dict, depth: int = 0) -> dict:
    """The schema of ``value`` among the branches of the union ``prop`` declares (``anyOf``, ``oneOf``, one inside
    another as an optional automation's trigger): the first one it fits (``_fits``), with what ``prop`` itself says
    (its title, its marks); ``prop`` resolved when it is no union."""
    prop = _referred(prop, defs)
    branches = [*prop.get("anyOf", []), *prop.get("oneOf", [])]
    if not branches or depth > 8:
        return resolved(prop, defs)
    outer = {key: inner for key, inner in prop.items() if key not in ("anyOf", "oneOf", "discriminator")}
    for branch in branches:
        branch = _referred(branch, defs)
        if branch.get("type") != "null" and _fits(value, branch):
            return fitting(value, {**branch, **outer}, defs, depth + 1)
    return resolved(prop, defs)


def said(value: Any, prop: dict, defs: dict, name: str, words: Words, inner: bool = False) -> Any:
    """``value`` in words as its schema ``prop`` declares it, at any depth: a moment as the person's language writes it
    (``Words.moment``), a value of a closed list by the label its app's models give it (``choice_label``), a record by
    its name (``Words.reference``) or else ``LEFT_OUT`` — left out of an object, none in a list (which still says how
    many it carries), as an attempt key (``ATTEMPT_KEY``) is, even empty; an amount (``MONEY``) inside an object or a
    list as the screen writes one on top (``Words.amount``), in the words of the object it is in (``Words.within``);
    what is none of them, or not what its schema declares (the write refuses it), as sent."""
    prop = fitting(value, prop, defs)
    if is_attempt_key(prop):
        return LEFT_OUT
    if value is None or value == "":
        return value
    if inner and is_money(name, prop) and isinstance(value, int) and not isinstance(value, bool):
        return words.amount(value)
    if REFERS in prop or (prop.get("format") == "uuid" and is_uuid(value)):
        return words.reference(value, prop)
    if prop.get("format") in MOMENTS and isinstance(value, str):
        spoken = words.moment(value, prop["format"])
        return value if spoken is None else spoken
    if "enum" in prop and isinstance(value, str | int) and not isinstance(value, bool):
        choice = choice_label(words.op.app_label, words.op.name.split(".")[1], name, value)
        return value if choice is None else str(choice)
    if isinstance(value, dict):
        props = prop.get("properties", {})
        extra = prop.get("additionalProperties")
        extra = extra if isinstance(extra, dict) else {}
        own = words.within(value, props, defs)
        spoken_items = {
            key: said(item, props.get(key, extra), defs, key if key in props else name, own, inner=True)
            for key, item in value.items()
        }
        return {key: item for key, item in spoken_items.items() if item is not LEFT_OUT}
    if isinstance(value, list):
        items, prefix = prop.get("items"), prop.get("prefixItems", [])
        items = items if isinstance(items, dict) else {}
        spoken_list = [
            said(item, prefix[i] if i < len(prefix) else items, defs, name, words, inner=True) for i, item in enumerate(value)
        ]
        return [None if item is LEFT_OUT else item for item in spoken_list]
    return value


def _in_words(value: Any, spoken: Any, prop: dict, defs: dict, name: str) -> bool:
    """Whether ``said`` put the item ``value`` of a list in words (``spoken``) as its schema ``prop`` declares it — a
    record (``REFERS`` or an id), a moment, a value of a closed list, an amount —, not as sent (``NAMED``)."""
    prop = fitting(value, prop, defs)
    if REFERS in prop or (prop.get("format") == "uuid" and is_uuid(value)):
        return True
    declared = prop.get("format") in MOMENTS or "enum" in prop or is_money(name, prop)
    return declared and spoken != value


def _said_in_words(value: list, spoken: list, prop: dict, defs: dict, name: str) -> bool:
    """Whether ``said`` put every item of the list ``value`` in words (``spoken``, item by item)."""
    prop = fitting(value, prop, defs)
    items, prefix = prop.get("items"), prop.get("prefixItems", [])
    items = items if isinstance(items, dict) else {}
    return all(
        _in_words(item, said_item, prefix[i] if i < len(prefix) else items, defs, name)
        for i, (item, said_item) in enumerate(zip(value, spoken, strict=True))
    )


def field(
    name: str, label: str, prop: dict, defs: dict, value: Any, money: dict | None = None, words: Words | None = None
) -> dict | None:
    """One datum of a card, as its schema ``prop`` declares it: a secret hidden (``hidden``) and, with the ``words``
    of its card, the rest in words (``said``); ``None`` when it names a record the card cannot name or is an attempt
    key. An amount carries ``signed`` when its schema declares it so and ``money`` when its currency is given (without
    it, the card paints it in the project's own); with words that price nothing, it is no amount but as sent.
    ``titled`` when ``label`` is the title its app wrote (``own_title``): the screen calls it so over its own word for
    a datum it knows by its name; a list, ``named`` when each of its items is said in words (``NAMED``)."""
    # The title of the property itself, as its caller's ``label``: a ``$ref``'s own is its schema class's name.
    titled = own_title(name, prop.get("title")) is not None
    sent = value = hidden(value, prop, defs)
    if words is not None:
        value = said(value, prop, defs, name, words)
    if value is LEFT_OUT:
        return None
    prop = resolved(prop, defs)
    if value is None or value == "" or value == []:
        kind = "empty"
    elif isinstance(value, bool):
        kind = "bool"
    elif isinstance(value, int) and is_money(name, prop) and (words is None or words.priced):
        kind = "money"
    elif isinstance(value, list):
        kind = "list"
    elif isinstance(value, dict):
        kind = "object"
    else:
        kind = "text"
    shown = {"name": name, "label": label, "kind": kind, "value": value}
    if titled:
        shown["titled"] = True
    if kind == "list" and words is not None and isinstance(sent, list) and _said_in_words(sent, value, prop, defs, name):
        shown[NAMED] = True
    if kind == "money" and is_signed(prop):
        shown["signed"] = True
    if kind == "money" and money is not None:
        shown["money"] = money
    return shown


def _over_records(op: Operation) -> bool:
    """Whether ``op`` is a dangerous write over the records its ``ids`` name."""
    schema = input_schema(op)
    ids = resolved(schema.get("properties", {}).get("ids", {}), schema.get("$defs", {}))
    return risk(op) == "high" and ids.get("type") == "array"


def blocked(op: Operation, arguments: dict) -> bool:
    """Whether ``arguments`` ask the dangerous write ``op`` over records (``ids``) and name none: not done from the
    chat, whatever else they say (its card says so; the model is never asked to name records for it)."""
    ids = arguments.get("ids")
    return _over_records(op) and not (isinstance(ids, list) and ids)


def card(op: Operation, arguments: dict, language: str, words: Words | None = None) -> dict:
    """What the person sees before ``op`` runs with ``arguments``: where it happens (``Words.app_name``), its action,
    each datum it sends by its name in ``language`` (``label``) and in ``words`` (``said``; ``PlainWords`` without
    them), its risk and, for a dangerous one, what to type (``confirm_word``) — how many records when it names them
    by ``ids``, and ``blocked`` when it names none (not from the chat)."""
    schema = input_schema(op)
    defs = schema.get("$defs", {})
    props = schema.get("properties", {})
    level = risk(op)
    refused = blocked(op, arguments)
    count = len(arguments["ids"]) if _over_records(op) and not refused else None
    words = (words if words is not None else PlainWords(op, language)).within(arguments, props, defs)
    with translation.override(language):
        shown = [
            # The title of the property itself: a ``$ref``'s own is its schema class's name.
            field(name, label(op, name, prop.get("title")), prop, defs, arguments[name], words.money(), words)
            for name, prop in props.items()
            if name in arguments
        ]
        fields = [one for one in shown if one is not None]
        word = str(count) if count else str(CONFIRM_WORD)
        app = words.app_name()
    return {
        "operation": op.name,
        "app": op.app_label,
        "app_name": app,
        "action": op.name.rsplit(".", 1)[-1],
        "risk": level,
        "fields": fields,
        "count": count,
        "confirm_word": word if level == "high" else "",
        "blocked": refused,
    }


def confirmed(card_: dict, typed: str) -> bool:
    """Whether ``typed`` is what the card asks, as the platform's ``ConfirmDialog`` compares it (``@erplora/ui``: spaces
    around and case ignored, accents not); a normal write asks nothing; a blocked one, never."""
    word = card_["confirm_word"]
    return not card_["blocked"] and (word == "" or typed.strip().casefold() == word.casefold())


# ── A tool, run as the person ────────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ToolOutcome:
    """``outcome``: ``ok``, ``error`` (the operation refused the data or the state: the model tells it), ``refused``
    (the person may not: no permission, the app off, a manager's approval) or ``cancelled`` (the person said no)."""

    outcome: str
    code: str
    content: str


def error_content(code: str, message: str, fields: dict | None = None) -> str:
    error: dict[str, Any] = {"code": code, "message": message}
    if fields:
        error["fields"] = fields
    return json.dumps({"error": error}, ensure_ascii=False)


#: What the model hears of data its operation refuses: which, and that it may ask again with them corrected.
NOT_FITTING = "Some data does not fit: nothing was done. Correct it and call the tool again."


def _validated(op: Operation, data: dict) -> tuple[ToolOutcome | None, Any]:
    """``data`` as ``op``'s input takes it: ``(None, the input)``, or ``(invalid_payload, None)`` with each field's
    message, as the operation's own validation says it (the values a closed list takes, the countries served…)."""
    try:
        return None, op.input.model_validate(data)
    except pydantic.ValidationError as exc:
        fields = {".".join(str(part) for part in error["loc"]) or "__all__": error["msg"] for error in exc.errors()}
        return ToolOutcome("error", "invalid_payload", error_content("invalid_payload", NOT_FITTING, fields)), None


def invalid_arguments(op: Operation, arguments: dict) -> ToolOutcome | None:
    """Why ``op``'s input refuses the model's ``arguments`` (``invalid_payload``, field by field), or ``None`` when it
    takes them. Asked before a write's card is drawn: the person never confirms data its operation will refuse; the
    model hears which, as the tool's result, and asks again with them corrected — one card, one yes. A dangerous
    write that names no record is not refused here: its card says it is not done from the chat (``blocked``)."""
    if blocked(op, arguments):
        return None
    failure, _ = _validated(op, arguments)
    return failure


def run(ctx: OperationContext, op: Operation, data: dict) -> tuple[ToolOutcome | None, Any]:
    """``op`` run with ``data`` for ``ctx``'s person, by its own operation: ``(None, its result)``, or why it did not
    run (``(outcome, None)``)."""
    failure, validated = _validated(op, data)
    if failure is not None:
        return failure, None
    try:
        return None, op(ctx, validated)
    except (PermissionDenied, AppInactive, Unauthorized) as exc:
        return ToolOutcome("refused", exc.code, error_content(exc.code, str(exc))), None
    except OperationError as exc:
        return ToolOutcome("error", exc.code, error_content(exc.code, str(exc), getattr(exc, "fields", None))), None


def run_tool(ctx: OperationContext, op: Operation, arguments: str) -> ToolOutcome:
    """Run ``op`` with the model's ``arguments`` (JSON text) for ``ctx``'s person, by its own operation."""
    try:
        data = json.loads(arguments or "{}")
    except ValueError:
        data = None
    if not isinstance(data, dict):
        return ToolOutcome("error", "invalid_payload", error_content("invalid_payload", "The arguments are not a JSON object."))
    failure, result = run(ctx, op, data)
    if failure is not None:
        return failure
    content = result.model_dump_json()
    if len(content) > MAX_RESULT_CHARS:
        content = content[:MAX_RESULT_CHARS] + " …(cut)"
    return ToolOutcome("ok", "", content)


# ── What a dangerous write will do, on its card ──────────────────────────────────────────────────────────────────


def preview(
    ctx: OperationContext,
    op: Operation,
    arguments: dict,
    *,
    words_of_answer: Callable[[Operation, OperationContext, dict], Words] = PlainWords.of_answer,
) -> tuple[ToolOutcome | None, list[dict] | None]:
    """What the dangerous write ``op`` will do with ``arguments``, as its app says it: the read its ``ai=`` names
    (``preview_of``: ``{"operation": <a query of its app>, "fields": [<data of its answer>]}``), run as ``ctx``'s
    person — their permissions, their business — with the data of the write its input takes. The card's data, by their
    names in the person's language and in the words of the answer (``words_of_answer``: its amounts in the currency it
    answers), in the order the app names them; what the read leaves empty or hides from this person is not there.
    ``(None, None)`` without a preview; ``(outcome, None)`` when it cannot be read: the write is not confirmed blind."""
    declared = preview_of(op)
    if declared is None:
        return None, None
    read = registry[declared["operation"]]
    failure, result = run(ctx, read, {name: value for name, value in arguments.items() if name in read.input.model_fields})
    if failure is not None:
        return failure, None
    answer = result.model_dump(mode="json")
    schema = output_schema(read)
    defs = schema.get("$defs", {})
    props = schema.get("properties", {})
    words = words_of_answer(read, ctx, answer)
    money = words.money()
    with translation.override(ctx.language):
        shown = [
            field(name, label(read, name, props[name].get("title")), props[name], defs, answer.get(name), money, words)
            for name in declared["fields"]
        ]
    return None, [one for one in shown if one is not None and one["kind"] != "empty"]


# ── The rounds of a request ──────────────────────────────────────────────────────────────────────────────────────


def rounds(messages: list[dict]) -> int:
    """The rounds of tools since the person's last message: the model's messages that asked for tools."""
    count = 0
    for message in reversed(messages):
        if message.get("role") == "user":
            break
        if message.get("role") == "assistant" and message.get("tool_calls"):
            count += 1
    return count
