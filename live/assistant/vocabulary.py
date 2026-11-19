"""The words a turn is read by: the actions they ask for and the words that name the same thing."""

import re


#: «Dar de baja», with its pronouns too («dale de baja», «darlos de baja»): a member leaves the business or a customer
#: a mailing (ERPlora/live#50).
_DEREGISTERS = tuple(
    f"{head} de baja"
    for head in (
        "da", "dar", "doy",
        *(f"{verb}{pronoun}" for verb in ("da", "dar") for pronoun in ("me", "le", "lo", "la", "nos", "les", "los",
                                                                      "las")),
    )
)
#: What a person says (Spanish or English) → the action of the operations that does it: the last part of an
#: operation's name or one of its words (``bulk_create``, ``set_image``). A phrase counts when its words come in a row,
#: and its words then ask for no other action and name nothing (``_PHRASE_NAMES`` aside): «get rid of» is no ``get``,
#: «set up» no ``set``, «turn on» no «turno».
VERBS = {
    # Noting writes something new down as «apunta» does («anota una cita para Ana»), adds to what there is or writes on
    # it («anota en la cita de Ana…»): what is named says which (ERPlora/live#64).
    "create": ("crea", "crear", "creame", "alta", "anade", "anadir", "agrega", "agregar", "apunta", "apuntar",
               "anota", "anotar", "registra", "registrar", "reservar", "nuevo", "nueva", "add", "create", "new",
               "register", "book"),
    # Registering writes something new down or adds it to what there is: «registra un cliente nuevo», «registra una
    # salida de 15 € en el turno» (ERPlora/live#95). Never English's «register», which is also the till itself.
    "add": ("anade", "anadir", "agrega", "agregar", "apunta", "apuntar", "anota", "anotar", "registra", "registrar",
            "mete", "meter", "ponle", "add"),
    "update": ("cambia", "cambiar", "modifica", "modificar", "actualiza", "actualizar", "edita", "editar", "pon",
               "ponle", "poner", "sube", "subir", "configura", "configurar", "ajusta", "ajustar", "ordena", "ordenar",
               "anota", "anotar", "apunta", "apuntar", "update", "change", "edit", "set", "set up", "configure",
               "reorder", "cambia el nombre", "cambiale el nombre", "cambiar el nombre", "ponle de nombre",
               "ponle el nombre", "ponle nombre", "pon de nombre", "pon el nombre", "poner el nombre",
               "change the name", "change its name"),
    "change": ("cambia", "cambiar", "change"),
    # Registering a device sets it up («registra esta tablet como Barra»): only what the command registers, and in
    # English only where it starts the command (``_registers``; ERPlora/live#117).
    "register": ("registra", "registrar", "register"),
    "reorder": ("ordena", "ordenar", "reorder"),
    "rename": ("renombra", "renombrar", "rename", "cambia el nombre", "cambiale el nombre", "cambiar el nombre",
               "ponle de nombre", "ponle el nombre", "ponle nombre", "pon de nombre", "pon el nombre",
               "poner el nombre", "change the name", "change its name"),
    "set": ("pon", "ponle", "poner", "asigna", "asignar", "cambia", "cambiar", "cambia el nombre",
            "cambiale el nombre", "cambiar el nombre", "ponle de nombre", "ponle el nombre", "ponle nombre",
            "pon de nombre", "pon el nombre", "poner el nombre", "set", "assign", "change", "change the name",
            "change its name"),
    # Taking away deletes, retires or withdraws: the thing named says which («retira la mesa», «retira el dispositivo»,
    # «retira su consentimiento»; ERPlora/live#64), as «se da de baja de la publicidad» withdraws (live#50).
    "delete": ("borra", "borrar", "borremos", "borrad", "elimina", "eliminar", "quita", "quitar", "retira", "retirar",
               "delete", "remove", "get rid"),
    "remove": ("borra", "borrar", "borremos", "borrad", "elimina", "eliminar", "quita", "quitar", "retira", "retirar",
               "delete", "remove", "get rid"),
    "retire": ("retira", "retirar", "retire"),
    "withdraw": ("retira", "retirar", "withdraw", *_DEREGISTERS),
    "erase": ("erase", "wipe", "borra sus datos", "borra todos sus datos", "borra los datos", "borrar sus datos",
              "borrar todos sus datos", "borrar los datos", "borrad todos sus datos", "borremos todos sus datos",
              "borremos sus datos"),
    "list": ("lista", "listar", "muestra", "muestrame", "ensena", "ensename", "ver", "dime", "cuantos", "cuantas",
             "busca", "buscar", "list", "show", "find", "search", "how many"),
    "count": ("cuantos", "cuantas", "contar", "count", "how many"),
    "get": ("dame", "datos", "detalle", "get", "detail"),
    "options": ("que se puede", "what can"),
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
    # Seating opens a table's check, or puts a parked one back at a table; a check taken to another table is
    # transferred (ERPlora/live#48).
    "open": ("abre", "abrir", "empieza", "inicia", "sienta", "sentar", "open", "start", "begin", "seat"),
    "restore": ("sienta", "sentar", "restaura", "restaurar", "seat", "restore"),
    "transfer": ("traslada", "trasladar", "transfiere", "transferir", "transfer"),
    "start": ("empieza", "inicia", "start", "begin"),
    "enable": ("activa", "activar", "activame", "reactiva", "reactivar", "enciende", "encender", "habilita",
               "habilitar", "enable", "activate", "reactivate", "turn on", "switch on", "quiero el modulo",
               "quiero la app", "quiero la aplicacion", "pon la app", "ponme la app", "pon el modulo",
               "ponme el modulo", "instala", "instalar", "install"),
    "disable": ("desactiva", "desactivar", "desactivo", "apaga", "apagar", "deshabilita", "deshabilitar", "disable",
                "deactivate", "turn off", "switch off"),
    # Switching a thing on or off is also activating or deactivating it, as a member, a price list or a rule are: the
    # thing named says which, in either language («apaga», «enciende»: ERPlora/live#79; «turn off», «switch on»:
    # ERPlora/live#82). «Activo» is left out: far more often it is what a thing is («los clientes activos»).
    "activate": ("activa", "activar", "reactiva", "reactivar", "enciende", "encender", "habilita", "habilitar",
                 "activate", "reactivate", "turn on", "switch on"),
    "deactivate": ("desactiva", "desactivar", "desactivo", "apaga", "apagar", "deshabilita", "deshabilitar",
                   "deactivate", "turn off", "switch off"),
    "approve": ("aprueba", "aprobar", "apruebo", "approve"),
    "reject": ("rechaza", "rechazar", "rechazo", "reject"),
    # «Pide» and «pedir» are left out: at a table they are what a customer orders («pide la cuenta»).
    "request": ("solicita", "solicitar", "solicito", "pido", "request"),
    "confirm": ("confirma", "confirmar", "confirmo", "confirm"),
    "terminate": (*_DEREGISTERS, "terminate"),
    "invite": ("invita", "invitar", "invite"),
    "print": ("imprime", "imprimir", "saca", "sacar", "print"),
    "refund": ("devuelve", "devolver", "reembolsa", "reembolsar", "refund"),
}
#: The words of a verb's phrase that still name what they name: «cambia el nombre» changes a name, «da de baja» names
#: the leave («baja») a member or a stock takes.
_PHRASE_NAMES = frozenset({"nombre", "name", "datos", "modulo", "app", "aplicacion", "baja"})
#: The phrases of ``VERBS`` that put a name on something («ponle el nombre», «change its name»), by their verb and what
#: follows it: said with what is named in between («pon al dispositivo que uso ahora el nombre «Barra»»), they count
#: as said in a row (ERPlora/live#47). Only a name with its article: «de nombre» and «nombre» alone may say what a thing
#: is called («el menú de nombre «Carta»»).
_NAMING: dict[str, tuple[tuple[str, ...], ...]] = {}
for _phrase in VERBS["rename"]:
    _head, *_rest = _phrase.split()
    if len(_rest) == 2 and _rest[0] in {"el", "the", "its"}:
        _NAMING[_head] = (*_NAMING.get(_head, ()), tuple(_rest))
#: The words before a name that make it what a thing is found by, not the name put on it («con el nombre»).
_FOUND_BY = frozenset({"con", "por", "de", "del", "bajo", "with", "by", "of", "under"})
#: The articles that open a verb's own object right after it («cambia el precio…», «change the price…»): such a verb
#: puts no name said later. What a name said apart is put on goes after «a», «al», «for», «on» («ponle a la lista el
#: nombre»).
_OWN_OBJECT = frozenset({"el", "la", "los", "las", "the"})
#: The word after which a verb's infinitive says what is not to be done («sin cambiar los pedidos», «sin borrarlo»), as
#: English says it with «without» and a form ``VERBS`` has not («without changing»): no action asked (ERPlora/live#60).
_WITHOUT = frozenset({"sin"})
#: The word that goes on with what is not to be done after a «sin» before it in the sentence («sin tocar caja ni cambiar
#: importes»): its infinitive asks for nothing either (ERPlora/live#74). With no «sin» before, «ni» is «not even»
#: («no sé ni cambiar el precio»), and the verb is asked. English says it with «or» and a gerund ``VERBS`` has not.
_NOR = frozenset({"ni"})
#: The word that makes a ``_NOR`` after it «not even» whatever ``_WITHOUT`` came before («tengo una mesa sin cobrar y no
#: puedo ni cerrar la caja»): the ``_NOR`` goes on from a ``_WITHOUT`` only with none of these between the two.
_NOT = frozenset({"no"})
#: The forms of the verbs that say what someone can or manages to do, and of the one that says what someone is let do
#: after whom it lets (``_TO_WHOM``: «me deja»; «lo dejo» leaves a thing). One said after the infinitive after a ``_NOR``
#: makes that «ni» «not even» whatever ``_WITHOUT`` came before («tengo una mesa sin cobrar, ni cerrar la caja me
#: deja», «ni cerrar puedo la caja»): its verb is asked (ERPlora/live#86).
_CAN = frozenset({"puedo", "puedes", "puede", "podemos", "pueden", "pude", "pudo", "podia", "podido", "consigo",
                  "consigue", "consegui", "consiguio", "conseguido"})
_LETS = frozenset({"deja", "dejan", "dejo", "dejaba"})
_TO_WHOM = frozenset({"me", "te", "le", "nos", "les"})
#: The words that open another clause: what someone can do said after one is that clause's, no «not even» («…ni
#: cambiar importes si puede», «…ni cambiar el fondo que me deja el turno», «…porque no puedo», «…pero no me deja»,
#: «…cuando puedes»). «Como» is left out: «ni cerrar la caja como antes puedo» still cannot even close it.
_OTHER_CLAUSE = frozenset({"si", "que", "porque", "pero", "cuando"})
#: The words after which a verb says what someone will do, not what is asked («I'll approve it», «we will open»).
_FUTURE = frozenset({"ll", "will"})
#: The words after which a thing is named for what another is («para las próximas ventas», «for the new sales»): to the
#: end of their sentence, it is not what a command switches (ERPlora/live#50).
_FOR_WHAT = frozenset({"para", "for"})
#: The words after which a thing is named as what another is of («los recordatorios de las citas», «the reminders of
#: the bookings»): what a switch turns on or off is named before them (``_switched``; ERPlora/live#89).
_OF = frozenset({"de", "del", "of"})
#: The action a yes to what was asked before says («sí, confírmalo»), and the words it is said with besides greetings.
_CONFIRMS = frozenset({"confirm"})
_YES = frozenset({"si", "yes", "claro", "adelante", "sure", "it", "that", "todo", "eso", "por", "favor", "please"})
_INFINITIVE = ("ar", "er", "ir")
#: The actions that only read: a question that asks for none of the others asks to know, not to do. Asked of nothing
#: named, they bring no tool: «¿cuántos…?» is no list of everything.
READ_VERBS = frozenset({"list", "get", "options", "count", "check", "stats"})
#: The actions that turn something on or off: of a setting a write takes («turn off the alerts»), they change it.
SWITCHES = frozenset({"enable", "disable"})
#: The actions of the operations that turn a thing on or off: its switch (``pricing.rule.deactivate``,
#: ``flow.recipe.enable``).
_TURNS = frozenset({"enable", "disable", "activate", "deactivate"})
#: The actions that change what a write takes.
_CHANGES = frozenset({"update", "set"})
#: The actions whose words also ask ``update``, for what has none of its own («ordena el menú»): where a tool does the
#: action itself, it comes before the change of the same thing.
_BEFORE_UPDATE = frozenset({"reorder"})
#: What a word that notes something down asks for («anota», «apunta»: ``VERBS``): writing it down, adding it to what
#: there is, or writing on what is named (``_WRITTEN_ON``: «anota en la cita de Ana…»), never on a setting a word names
#: in passing («anota una salida de 15 € de la caja»: no setting of the till; ERPlora/live#88).
_NOTES = frozenset({"create", "add", "update"})
_WRITTEN_ON = frozenset({"update"})
#: The action of the words that put something somewhere («anota», «apunta», «añade», «mete»): where they put it, said
#: before it, is no thing they act on («mete en el turno una entrada»). Where other verbs act, said first, is what they
#: act on («borra del historial la cuenta», «pon en la web el horario»).
_PUTS = frozenset({"add"})
#: The word after which a word that notes something down or puts it somewhere says what happened («registra que entran
#: 20 cafés…», «apunta que Carmen prefiere las mañanas»): the create and the add it asks for note that down, and when
#: the fact is another tool's doing, what it names is no datum they take (ERPlora/live#116). Said later, it says what is
#: written where («registra en la ficha de Ana que…»).
_THAT = frozenset({"que"})
_STATES = frozenset({"create", "add"})
#: The forms of «haber» that, right before a participle in «-ado», say what happened in the plural («han entrado»,
#: «habían entrado»): told or noted down, the compound past is also its present («entran»), said before it, so it names
#: what the present names and is what a word that notes it down acts on («apunta que han entrado 12 unidades de tarta»
#: receives the goods, as «apunta que entran…» does; ERPlora/live#122). Never of money said right after it («han
#: entrado 100 €»), nor when that present asks for an action («han cuadrado» is no «cuadran»), nor in a question.
_HAVE = frozenset({"han", "habian"})
_PARTICIPLE, _PRESENT = "ado", "an"
#: Setting a device up (``VERBS``: «registra esta tablet»): asked only where the word is the command (``_registers``),
#: and of a tool only when what the command acts on is that tool's thing — a tablet named as where something is
#: registered («registra en esta tablet una salida de 15 €») is not set up (ERPlora/live#117).
_REGISTERS = frozenset({"register"})
#: What says, right after the word that registers, where or with what it is done: the device named so is not what is
#: registered («registra desde esta tablet una salida de 20 €», «registra con esta tablet…»).
_REGISTERED_FROM = frozenset({"desde", "con", "on", "from"})
#: The words that take something out: Spanish's «saca» («sácame», «sacar») and English's «take» with its «out». Of money
#: (``_money``), right after them or after where it comes from («saca 15 € de la caja», «saca de la caja 15 €», «take
#: 15 € out of the till», «take out 15 €»), they note the money taken out down (``_TAKEN_OUT``: adding it, as the till's
#: cash-out), never export nor print it, and act on nothing named after it («para comprar hielo» is what it is for).
#: Of anything else they are what they were: «saca el listado» exports, «saca 2 copias del tique» prints, «take 5 out
#: of stock» says how many (ERPlora/live#118).
_TAKES_OUT = frozenset({"saca", "sacar"})
_TAKE, _OUT = "take", "out"
_TAKEN_OUT = frozenset({"add"})
#: What money taken out is, which Spanish's «saca» does not say: an outflow of the till («una salida de 15 €»). English
#: says it with its «out».
_OUTFLOW = "salida"
#: The words that say money came in («entran 100 € en el turno», «ha entrado 100 € en caja»): of money, right after
#: them or after where it comes in (``_money_after``), they name the till's cash (``_TILL``), never what a project names
#: by them (the goods «entran» receive in the Hub), and are no thing the command acts on (ERPlora/live#123). Of anything
#: else they are what they were: «entran 12 unidades de tarta» are goods.
_COMES_IN = frozenset({"entra", "entran", "entrado"})
_TILL = "caja"
#: A number said with its currency's name after it («50 euros») or its sign before or after it, decimals too («15 €»,
#: «12,50 €», «€15», «$20»): the sign is no word, so it is read from the text.
_CURRENCIES = frozenset({"euro", "euros", "eur", "dolar", "dolares", "dollar", "dollars", "libra", "libras", "pound",
                         "pounds"})
_WITH_ITS_SIGN = re.compile(r"(\d+)(?:[.,]\d+)?\s?[€$£]|[€$£]\s?(\d+)")
#: The words that open a phrase of its own, as an article, a possessive or «otro» do («en la caja», «su teléfono», «un
#: documento», «otra salida»), but those of ``STOP_WORDS`` («una», «esta», «sus»): what is put after where it is put
#: is named in one.
_DETERMINERS = frozenset({"el", "la", "su", "mi", "tu", "un", "otro", "otra", "otros", "otras"})
#: The words that say where a thing is noted or whose it is, not what is noted down («apunta en la ficha de Ana su
#: teléfono nuevo», «anota de la caja una salida»): with its article («del», «al»), or before one or another word that
#: names nothing yet («de la caja», «en su ficha»). Before a name, what follows is the datum («el número de teléfono»,
#: «la subida de precio»).
_WHERE = frozenset({"en", "de", "del", "a", "al"})
_WITH_ITS_ARTICLE = frozenset({"del", "al"})
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
#: Words after which a verb starts another command inside a sentence («y muestra», «and show», «luego busca»).
_THEN = frozenset({"y", "e", "luego", "despues", "tambien", "and", "then", "also"})
#: The pronouns an English command says after it («show me», «find us»), as a Spanish one carries them at its end.
_PRONOUNS_AFTER = frozenset({"me", "us"})
#: Commands said with their pronouns whose verb no other word of ``VERBS`` says: «dame» (give me).
_WITH_PRONOUNS = frozenset({"dame"})
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
    ("regla", "rule"),
    ("metodo", "method"),
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
    ("comensal", "guest"),
    ("recordatorio", "reminder"),
    # Only the phrases: «tema» alone is also the matter, and «modo» a way («de modo que»).
    ("theme", "modo oscuro", "modo claro", "tema oscuro", "tema claro"),
    ("sentar", "sienta", "seat"),
    ("ajustes", "ajuste", "configuracion", "configurar", "configura", "settings", "setting", "setup", "configure",
     "set up"),
)
_WORD = re.compile(r"[a-z0-9]+")
#: What ends a sentence or a quote: its first word may be a command («Ficha la entrada»), a question word, a name.
_BREAK = re.compile(r"[«»\"“”()\[\].,;:!?¿¡\n]+")
#: ``_BREAK`` keeping what it cuts at, to tell a comma from the rest.
_BREAK_KEPT = re.compile(f"({_BREAK.pattern})")
#: Words kept whole: cut, they would be another word's stem («personal», the staff, is not «persona»).
_WHOLE = frozenset({"personal"})
#: Words kept apart from another's stem (as said, or without their plural «s»): «tablet» is no «table», «compartido»
#: no «company», «peluquería» (the business) no «peluquero» (its staff), «carta» (the menu) no «cart», «contrato» and
#: «contraseña» no «control», «recibo» (a receipt) no «recibir», «ficha» (a customer's card) no «fichar»,
#: «settings» no «set», «registro» (a record) no «register» (the till), «comensal» (a diner) no «comentario» nor
#: «comenzar», «listo» (ready, done) no «lista» (to list, a list), «disponible» (available) no «dispositivo»
#: (a device), «sella» (to seal) no «sell» nor «sellable», «existir» (to exist, «existing») no «existencias» (the
#: stock, which keep their stem), «producción» («production») no «producto» and «comprobar» (to check) no «compra»
#: (ERPlora/live#71), «recordatorio» (a reminder) no «record» nor «recordar» (ERPlora/live#89), and «ordenador» (a
#: computer) no «ordena», «ordenar» nor «orden» (to put in order, an order; ERPlora/live#61).
_APART_WORDS = {"ficha": "ficha", "carta": "carta", "recibo": "recibo", "registro": "registro", "fiche": "fichar",
                "ficho": "fichar", "listo": "listo", "selle": "sellar", "sellen": "sellar"}
_APART_PREFIXES = (
    ("peluqueri", "peluqueri"), ("contrasen", "contrasen"), ("compart", "compart"), ("contract", "contrat"),
    ("contrat", "contrat"), ("receipt", "receipt"), ("fichaj", "fichar"), ("fichar", "fichar"), ("fichad", "fichar"),
    ("fichand", "fichar"), ("ficham", "fichar"), ("fichal", "fichar"), ("tablet", "tablet"), ("setting", "setting"),
    ("comensal", "comensal"), ("dispon", "dispon"), ("sellab", "sellab"), ("sella", "sellar"), ("sello", "sellar"),
    ("sellem", "sellar"), ("sellei", "sellar"), ("existenci", "exist"), ("exist", "existir"),
    ("produccion", "produccion"), ("production", "produccion"), ("comprob", "comprobar"), ("comprue", "comprobar"),
    ("recordatori", "recordatori"), ("ordenador", "ordenador"),
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
