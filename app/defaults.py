"""Valores padrão: temas visuais e as vitrines de anúncio de cada fã clube novo."""

VINTAGE_THEME = {
    "paper": "#F2E8D5",
    "paper2": "#E9DCC3",
    "cream": "#FFF8EC",
    "ink": "#211B16",
    "inkSoft": "#5A4B3E",
    "accent": "#B8461A",
    "accentFg": "#FFF8EC",
    "accent2": "#E0A526",
    "accent3": "#D9782A",
    "deep": "#6B3A1F",
    "fontDisplay": "var(--font-shrikhand), Georgia, serif",
    "fontBody": "var(--font-fraunces), Georgia, serif",
    "fontLabel": "var(--font-space-mono), ui-monospace, monospace",
}

BLANK_THEME = {
    "paper": "#F6F7F9",
    "paper2": "#E6E9EE",
    "cream": "#FFFFFF",
    "ink": "#14171C",
    "inkSoft": "#5B6370",
    "accent": "#2F5BD3",
    "accentFg": "#FFFFFF",
    "accent2": "#9DB4F0",
    "accent3": "#5F82E0",
    "deep": "#1E3F9E",
    "fontDisplay": "var(--font-plex-sans), system-ui, sans-serif",
    "fontBody": "var(--font-plex-sans), system-ui, sans-serif",
    "fontLabel": "var(--font-plex-mono), ui-monospace, monospace",
}

MODULES = ("mural", "agenda", "pickup", "loja", "drops", "photo", "ads", "resale")
# Módulos de cada fã clube novo: todos ligados, menos a revenda (saiu do app e fica escondida até segunda ordem).
DEFAULT_MODULES = {**{k: True for k in MODULES}, "resale": False}

# key, nome, onde, formato, diagrama (top, altura em px de um celular de 96 px de altura)
# O catálogo das vitrines à venda em cada ambiente de cantor. A key é fixa: ela liga a vitrine ao lugar do app.
DEFAULT_AD_SLOTS = [
    # Entrada e Início
    ("entrada", "Modal de entrada do app", "Ao abrir o app · modal logo depois do login", "Arte + título + texto + link", 22, 52),
    ("home", "Início · abaixo do primeiro post", "Início · logo abaixo do primeiro card da tela", "Arte + título + texto + link", 24, 16),
    # Feeds
    ("mural", "Mural · depois de cada post", "Mural · um anúncio a cada 1 post", "Post com imagem + link", 36, 18),
    ("feed_clubes", "Fã clubes · a cada 2 posts", "Feed de cada fã clube e Comunidade filtrada por clube · um anúncio a cada 2 posts", "Post com imagem + link", 50, 18),
    ("noticias", "Notícias · post aleatório", "Comunidade · um post patrocinado em posição aleatória entre as notícias", "Post com imagem + link", 62, 18),
    # Roleta (PicKup da sorte)
    ("pickup", "Roleta · camada 1", "Roleta · primeira camada, uma fatia com a marca e o prêmio", "Logo + prêmio ou cupom", 18, 44),
    ("pickup_2", "Roleta · camada 2", "Roleta · segunda camada, uma fatia com a marca e o prêmio", "Logo + prêmio ou cupom", 18, 44),
    ("pickup_3", "Roleta · camada 3", "Roleta · terceira camada, uma fatia com a marca e o prêmio", "Logo + prêmio ou cupom", 18, 44),
    ("pickup_4", "Roleta · camada 4", "Roleta · quarta camada, uma fatia com a marca e o prêmio", "Logo + prêmio ou cupom", 18, 44),
    ("pickup_video", "Roleta · vídeo antes de girar", "Roleta · vídeo obrigatório antes de girar", "Vídeo até 60 s (MP4) + título + link", 10, 76),
    ("pickup_resgate", "Roleta · vídeo ao pegar o brinde", "Roleta · vídeo quando o fã toca para pegar o brinde", "Vídeo até 60 s (MP4) + título + link", 10, 76),
    # Loja
    ("loja", "Loja · em cima da lojinha", "Loja · topo da página, acima dos produtos", "Banner 16:9 + link", 16, 20),
    ("loja_compra", "Loja · depois da compra", "Loja · tela de pedido confirmado, depois de comprar a camiseta", "Arte + título + texto + link", 40, 30),
]

# Vitrines que existiram e saíram do catálogo (o script scripts/atualizar_vitrines.py as remove, com --apply).
RETIRED_ENV_SLOTS = ("evento", "drops", "feed_2", "feed_3", "feed_4")
RETIRED_CLUB_SLOTS = ("mural", "feed_2", "feed_3")  # o feed dos clubes agora é a vitrine "feed_clubes" do ambiente

NEW_CLUB_COLORS = ["#2F5BD3", "#1F7A4D", "#7A3FB8", "#14171C"]

# Vitrines de cada fã clube (a key final fica "{slug do clube}.{key}").
CLUB_AD_SLOTS = [
    ("home", "Card do fã clube", "Página do fã clube · topo", "Arte + título + texto + link", 20, 16),
    ("pickup", "Fatia patrocinada no PicKup do clube", "Roleta do fã clube · uma fatia com a marca", "Logo + prêmio ou cupom", 18, 44),
]

MAX_CLUB_STAFF = 10  # por fã clube: 1 dono + ajudantes
MASTER_CLUB_SLUG = "oficial"


# Experiências que o fã pode adicionar ao ingresso (chave -> nome mostrado e usado no rótulo do ingresso).
ADDON_LABELS = {
    "jantar": "Jantar com o Vintage",
    "camarim": "Meet & greet no camarim",
    "pre": "Pré-esquenta",
    "after": "After",
    "hotel": "Hotel com hospedagem",
    "transfer": "Transfer ida e volta",
}
