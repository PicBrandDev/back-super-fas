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

MODULES = ("mural", "agenda", "pickup", "loja", "drops", "photo", "ads")

# Texto antigo do "onde" da vitrine do Mural (a subida da API troca pelo novo se ninguém editou).
OLD_MURAL_WHERE = "Mural · aba Galera, a cada [n] posts"
MURAL_WHERE = "Mural · post pequeno entre os cartazes, a cada 4"

# key, nome, onde, formato, diagrama (top, altura)
DEFAULT_AD_SLOTS = [
    ("home", "Card da Home", "Início · logo acima do Drop News", "Arte + título + texto + link", 20, 16),
    ("mural", "Post patrocinado no Mural", MURAL_WHERE, "Post com imagem + link", 28, 24),
    ("evento", "Patrocínio de evento", "Tela do evento · faixa acima de Onde comprar", "Logo + texto + link", 58, 12),
    ("pickup", "Prêmio patrocinado no PicKup", "Roleta · uma fatia com a marca e o prêmio", "Logo + prêmio ou cupom", 18, 44),
    ("loja", "Banner da Loja", "Loja · topo da página", "Banner 16:9 + link", 16, 20),
    ("drops", "“Apresenta” no Drops Hits", "Player de prévias · “[Marca] apresenta”", "Logo", 22, 10),
    # Anúncios dentro do app (GET /artists/{slug}/ads/in-app)
    ("entrada", "Anúncio de entrada", "Ao abrir o app · modal logo após o login", "Arte + título + texto + link", 22, 52),
    ("pickup_video", "Vídeo antes do giro", "Roleta · vídeo de 30 s obrigatório antes de girar", "Vídeo até 60 s (MP4) + título + link", 10, 76),
    ("pickup_resgate", "Anúncio no resgate do prêmio", "Roleta · modal quando o fã ganha um prêmio", "Arte + título + texto + link", 26, 44),
    # Mais posições entre os posts do feed do cantor (a "mural" é a 1ª, a cada 4 posts)
    ("feed_2", "Feed do Vintage · posição 2", "Feed · entre os posts, depois do 8º", "Post com imagem + link", 44, 24),
    ("feed_3", "Feed do Vintage · posição 3", "Feed · entre os posts, depois do 12º", "Post com imagem + link", 60, 24),
    ("feed_4", "Feed do Vintage · posição 4", "Feed · entre os posts, depois do 16º", "Post com imagem + link", 76, 20),
]

NEW_CLUB_COLORS = ["#2F5BD3", "#1F7A4D", "#7A3FB8", "#14171C"]

# Vitrines de cada fã clube (a key final fica "{slug do clube}.{key}").
CLUB_AD_SLOTS = [
    ("home", "Card do fã clube", "Página do fã clube · topo", "Arte + título + texto + link", 20, 16),
    ("mural", "Post patrocinado no mural do clube", "Mural do fã clube · entre os posts da galera", "Post com imagem + link", 28, 24),
    ("pickup", "Fatia patrocinada no PicKup do clube", "Roleta do fã clube · uma fatia com a marca", "Logo + prêmio ou cupom", 18, 44),
    ("feed_2", "Feed do clube · posição 2", "Feed do fã clube · entre os posts, depois do 8º", "Post com imagem + link", 44, 24),
    ("feed_3", "Feed do clube · posição 3", "Feed do fã clube · entre os posts, depois do 12º", "Post com imagem + link", 60, 24),
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
}
