"""Vaste kleurenset voor categorieën.

De kleur wordt als sleutel opgeslagen en via een CSS-klasse (`.cat-<sleutel>`)
getoond, zodat er geen inline styles nodig zijn (strikte CSP). Alle kleuren
halen minimaal 3:1 contrast op wit (eis voor niet-tekstelementen).
"""

CATEGORY_COLORS: dict[str, tuple[str, str]] = {
    "blue": ("Blauw", "#4c7dd8"),
    "sky": ("Hemelsblauw", "#3f8fb5"),
    "teal": ("Turquoise", "#2e9c8f"),
    "green": ("Groen", "#3e9b5f"),
    "olive": ("Olijf", "#7d8b2e"),
    "orange": ("Oranje", "#b8771f"),
    "red": ("Rood", "#c8503c"),
    "pink": ("Roze", "#c2577f"),
    "purple": ("Paars", "#8a6bd1"),
    "brown": ("Bruin", "#8b6a4f"),
    "slate": ("Leisteen", "#5e6b7a"),
}

DEFAULT_COLOR = "slate"
