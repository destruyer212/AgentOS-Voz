"""Restriccion de zona de delivery: El Olivar Grill esta en Puente Piedra
(Lima Norte) y solo reparte cerca. Pedido explicito del negocio: nada de
delivery fuera de Lima, y dentro de Lima solo a distritos realmente
cercanos al local -- no a Lima entera.

Distritos limitrofes de Puente Piedra verificados (no adivinados): Ancon
(norte), Carabayllo (este), Comas y Los Olivos (sureste), San Martin de
Porres (sur). Ventanilla y Mi Peru tambien limitan por el oeste, pero son
de la Provincia Constitucional del Callao, no del departamento de Lima --
fuera de la zona a proposito, siguiendo el pedido explicito de "solo
Lima".

Este chequeo es deliberadamente conservador en un solo sentido: SOLO
rechaza cuando encuentra evidencia positiva de que la direccion esta
fuera de zona (menciona otro departamento, u otro distrito de
Lima/Callao conocido). Una direccion ambigua sin ningun distrito
mencionado ("Jr. Los Pinos 123") se deja pasar -- mejor no bloquear a un
cliente real de la zona por una direccion incompleta que rechazar mal.
"""

from app.domain.text_utils import normalize_text

# Los 24 departamentos del Peru (Callao es Provincia Constitucional, no
# departamento, pero se trata igual aca: si alguien lo menciona, tampoco
# es zona de reparto).
PERU_DEPARTMENTS_OUTSIDE_LIMA = {
    "amazonas", "ancash", "apurimac", "arequipa", "ayacucho", "cajamarca",
    "callao", "cusco", "cuzco", "huancavelica", "huanuco", "ica", "junin",
    "la libertad", "lambayeque", "loreto", "madre de dios", "moquegua",
    "pasco", "piura", "puno", "san martin", "tacna", "tumbes", "ucayali",
}

# Distritos de Lima (o Callao) donde SI llega el delivery -- cerca de
# Puente Piedra, verificado contra limites reales del distrito.
NEARBY_DELIVERY_DISTRICTS = {
    "puente piedra",
    "ancon",
    "carabayllo",
    "comas",
    "los olivos",
    "san martin de porres",
    "smp",
}

# Distritos de Lima/Callao bien conocidos que NO estan cerca de Puente
# Piedra -- lista no exhaustiva a proposito (Lima tiene 43 distritos),
# cubre los que un cliente real mencionaria. Si el cliente nombra un
# distrito que no esta ni aca ni en NEARBY_DELIVERY_DISTRICTS, no se
# rechaza (ver docstring del modulo) -- pasa como si no hubiera dicho
# ningun distrito.
KNOWN_FAR_DISTRICTS = {
    "cercado de lima", "rimac", "brena", "la victoria", "san luis",
    "san borja", "surco", "santiago de surco", "san isidro", "miraflores",
    "barranco", "chorrillos", "surquillo", "jesus maria", "lince",
    "magdalena", "magdalena del mar", "pueblo libre", "san miguel", "ate",
    "santa anita", "el agustino", "san juan de lurigancho", "sjl",
    "la molina", "cieneguilla", "chaclacayo", "chosica", "lurigancho",
    "villa el salvador", "villa maria del triunfo", "san juan de miraflores",
    "lurin", "pachacamac", "punta hermosa", "punta negra", "san bartolo",
    "pucusana", "independencia", "bellavista", "la perla", "la punta",
    "carmen de la legua", "ventanilla", "mi peru",
}

_DELIVERY_ZONE_MESSAGE = (
    "Uy, por ahora el delivery solo llega cerca de Puente Piedra "
    "(Comas, Los Olivos, Carabayllo, Ancón o San Martín de Porres). "
    "¿Prefieres recoger tu pedido en el local?"
)

_ASK_DISTRICT_MESSAGE = (
    "Perfecto, ¿y a qué distrito pertenece esa dirección? Hacemos delivery "
    "cerca de Puente Piedra (Comas, Los Olivos, Carabayllo, Ancón o San "
    "Martín de Porres)."
)


def delivery_zone_rejection_message(address: str) -> str | None:
    """None si la direccion parece estar dentro de la zona de reparto (o no
    da evidencia de lo contrario). Un mensaje listo para decir/mostrar si
    la direccion menciona un lugar claramente fuera de zona."""
    lowered = normalize_text(address)

    if any(district in lowered for district in NEARBY_DELIVERY_DISTRICTS):
        return None

    if any(dept in lowered for dept in PERU_DEPARTMENTS_OUTSIDE_LIMA):
        return _DELIVERY_ZONE_MESSAGE

    if any(district in lowered for district in KNOWN_FAR_DISTRICTS):
        return _DELIVERY_ZONE_MESSAGE

    return None


def address_names_known_district(address: str) -> bool:
    """True si la direccion ya menciona un distrito reconocible (cercano o
    lejano) o un departamento -- es decir, si delivery_zone_rejection_message
    tiene con que decidir de verdad. Usado para distinguir "direccion sin
    distrito" (hay que preguntar cual es) de "direccion con distrito ya
    aceptado" (no hace falta preguntar de nuevo)."""
    lowered = normalize_text(address)
    return (
        any(district in lowered for district in NEARBY_DELIVERY_DISTRICTS)
        or any(dept in lowered for dept in PERU_DEPARTMENTS_OUTSIDE_LIMA)
        or any(district in lowered for district in KNOWN_FAR_DISTRICTS)
    )


def ask_district_message() -> str:
    return _ASK_DISTRICT_MESSAGE
