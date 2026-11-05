"""Catálogo das vitrines: categorias, o que cada uma aceita (título, texto, foto, vídeo) e o preço padrão por view e por clique.

Sem importar nenhum modelo, para servir ao banco, às rotas e à criação das vitrines.
Os preços são em milésimos de real (R$ 0,012 = 12): view e clique custam frações de centavo.
"""

ELEMENT_KEYS = ("title", "text", "image", "video")

# O que a vitrine aceita do anúncio, por vitrine (a key sem o prefixo do fã clube).
ELEMENTS: dict[str, list[str]] = {
    "entrada": ["title", "text", "image"],
    "home": ["title", "text", "image"],
    "mural": ["title", "text", "image"],
    "feed_clubes": ["title", "text", "image"],
    "noticias": ["title", "text", "image"],
    "pickup": ["title", "image"],
    "pickup_2": ["title", "image"],
    "pickup_3": ["title", "image"],
    "pickup_4": ["title", "image"],
    "pickup_video": ["title", "text", "video"],
    "pickup_resgate": ["title", "text", "image", "video"],
    "loja": ["title", "image"],
    "loja_compra": ["title", "text", "image"],
}

# Preço padrão: R$ 0,012 por view (R$ 12 por mil) e R$ 0,80 por clique.
DEFAULT_VIEW_MILLI = 12
DEFAULT_CLICK_MILLI = 800

# categoria -> (nome, ordem)
CATEGORIES = {
    "entrada": ("Entrada e Início", 0),
    "feed": ("Feeds", 1),
    "roleta": ("Roleta", 2),
    "loja": ("Loja", 3),
    "clubes": ("Fã clubes", 4),
}


def base_key(key: str) -> str:
    return key.split(".", 1)[-1]


def slot_elements(key: str) -> list[str]:
    return list(ELEMENTS.get(base_key(key), list(ELEMENT_KEYS)))


def slot_category(key: str) -> str:
    """A categoria da vitrine pela key. As vitrines dos fã clubes ("clube.home") ficam em "Fã clubes"."""
    if "." in key:
        return "clubes"
    base = base_key(key)
    if base in ("entrada", "home"):
        return "entrada"
    if base in ("mural", "feed_clubes", "noticias"):
        return "feed"
    if base.startswith("pickup"):
        return "roleta"
    if base.startswith("loja"):
        return "loja"
    return "clubes"
