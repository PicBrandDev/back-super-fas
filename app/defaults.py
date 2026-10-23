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

MODULES = ("mural", "agenda", "pickap", "loja", "drops", "photo", "ads")

# Texto antigo do "onde" da vitrine do Mural (a subida da API troca pelo novo se ninguém editou).
OLD_MURAL_WHERE = "Mural · aba Galera, a cada [n] posts"
MURAL_WHERE = "Mural · post pequeno entre os cartazes, a cada 4"

# key, nome, onde, formato, diagrama (top, altura)
DEFAULT_AD_SLOTS = [
    ("home", "Card da Home", "Início · logo acima do Drop News", "Arte + título + texto + link", 20, 16),
    ("mural", "Post patrocinado no Mural", MURAL_WHERE, "Post com imagem + link", 28, 24),
    ("evento", "Patrocínio de evento", "Tela do evento · faixa acima de Onde comprar", "Logo + texto + link", 58, 12),
    ("pickap", "Prêmio patrocinado no PicKap", "Roleta · uma fatia com a marca e o prêmio", "Logo + prêmio ou cupom", 18, 44),
    ("loja", "Banner da Loja", "Loja · topo da página", "Banner 16:9 + link", 16, 20),
    ("drops", "“Apresenta” no Drops Hits", "Player de prévias · “[Marca] apresenta”", "Logo", 22, 10),
    # Anúncios dentro do app (GET /artists/{slug}/ads/in-app)
    ("entrada", "Anúncio de entrada", "Ao abrir o app · modal logo após o login", "Arte + título + texto + link", 22, 52),
    ("pickap_video", "Vídeo antes do giro", "Roleta · vídeo de 30 s obrigatório antes de girar", "Vídeo até 60 s (MP4) + título + link", 10, 76),
    ("pickap_resgate", "Anúncio no resgate do prêmio", "Roleta · modal quando o fã ganha um prêmio", "Arte + título + texto + link", 26, 44),
]

NEW_CLUB_COLORS = ["#2F5BD3", "#1F7A4D", "#7A3FB8", "#14171C"]

# Vitrines de cada fã clube (a key final fica "{slug do clube}.{key}").
CLUB_AD_SLOTS = [
    ("home", "Card do fã clube", "Página do fã clube · topo", "Arte + título + texto + link", 20, 16),
    ("mural", "Post patrocinado no mural do clube", "Mural do fã clube · entre os posts da galera", "Post com imagem + link", 28, 24),
    ("pickap", "Fatia patrocinada no PicKap do clube", "Roleta do fã clube · uma fatia com a marca", "Logo + prêmio ou cupom", 18, 44),
]

MAX_CLUB_STAFF = 10  # por fã clube: 1 dono + ajudantes
MASTER_CLUB_SLUG = "oficial"
