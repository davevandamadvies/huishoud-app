"""Vaste kleurenset en symbolen voor categorieën.

De kleur wordt als sleutel opgeslagen en via een CSS-klasse (`.cat-<sleutel>`)
getoond, zodat er geen inline styles nodig zijn (strikte CSP). Elke kleur heeft
een volle tint (symboolblokje, vinkcirkel) en een zacht vlak (taakkaart); de
volle tint haalt minimaal 3:1 op wit en op het eigen vlak. Een symbool is een
sleutel naar `templates/icons/cat/<sleutel>.svg`.
"""

CATEGORY_COLORS: dict[str, tuple[str, str]] = {
    "blue": ("Blauw", "#3d6fe0"),
    "sky": ("Hemelsblauw", "#2a7fae"),
    "teal": ("Turquoise", "#11888c"),
    "green": ("Groen", "#2b8a52"),
    "olive": ("Olijf", "#6f7f1a"),
    "orange": ("Oranje", "#c96510"),
    "red": ("Rood", "#d23f55"),
    "pink": ("Roze", "#c2447f"),
    "purple": ("Paars", "#7c59d4"),
    "brown": ("Bruin", "#8a6446"),
    "slate": ("Leisteen", "#5a6878"),
}

DEFAULT_COLOR = "slate"

# Zachte vlakken bij de kleuren hierboven (achtergrond van een taakkaart)
CATEGORY_SOFT: dict[str, str] = {
    "blue": "#e2eafb",
    "sky": "#dcf0f8",
    "teal": "#d6efef",
    "green": "#daf1e2",
    "olive": "#eef1d2",
    "orange": "#fce8d4",
    "red": "#fadde2",
    "pink": "#f9e0ee",
    "purple": "#e9e1fa",
    "brown": "#f1e6dc",
    "slate": "#e5e9ee",
}

CATEGORY_ICONS: dict[str, str] = {
    "sparkle": "Schoonmaak",
    "house": "Huis",
    "car": "Auto",
    "leaf": "Tuin",
    "plant": "Planten",
    "router": "Techniek",
    "wrench": "Klussen",
    "trash": "Afval",
    "shirt": "Was",
    "cutlery": "Keuken",
    "paw": "Huisdier",
    "cart": "Boodschappen",
    "euro": "Geldzaken",
    "drop": "Water",
    "bolt": "Energie",
    "bed": "Slaapkamer",
    "bike": "Fiets",
    "heart": "Zorg",
    "tag": "Overig",
}

DEFAULT_ICON = "tag"
