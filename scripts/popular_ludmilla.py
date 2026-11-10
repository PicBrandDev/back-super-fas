"""Alimenta o ambiente da Ludmilla com dados de exemplo para a apresentação.

Mesmo formato do popular_anitta.py, com o conteúdo do modo exemplo do front (src/lib/mock-ludmilla.ts):
fã clubes (Oficial, RJ, Ludmillers SP, BA e MG, com donos), fãs e membros, feed (posts oficiais e dos fãs, com comentários),
agenda de shows com ingresso, brindes e pacotes das agências, compras de experiências, a loja de óculos (Chilli Beans x Ludmilla,
com pedidos e visitas), Drops Hits, benefícios dos membros, roleta (prêmios, giros e ganhadores), ranking de compartilhamentos
e caronas por show. Os fãs são os que já existem no banco (entram também na Ludmilla); os donos dos clubes são contas novas.

Idempotente: cada bloco só roda se aquela parte ainda estiver vazia. Não cria foto de post nenhuma (o feed sai só com texto);
as fotos dos produtos apontam para /media/ludmilla/*.jpg, que vem do front.

Servidor: cd ~/front-super-fas && sudo docker compose exec -T api python - < ../back-super-fas/scripts/popular_ludmilla.py
Local:    PYTHONPATH=. python scripts/popular_ludmilla.py   (rode antes o criar_ludmilla.py, igual ao criar_anitta.py com o slug "ludmilla")
"""

import random
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select

from app import models as m
from app.carpool.models import B_CANCELLED, B_PAID, B_REFUNDED, B_RESERVED, R_CANCELLED, R_OPEN, Ride, RideBooking, RideLedger
from app.db import SessionLocal
from app.routers.clubs import create_club
from app.security import hash_password, temp_password

SLUG = "ludmilla"
rnd = random.Random(2026)
agora = datetime.now(timezone.utc)

CLUBES = [
    ("Fã-clube RJ", "Rio de Janeiro", "Caravana pro Numanice, ponto marcado na grade e roda de pagode no fim.", "Bia Santos"),
    ("Ludmillers SP", "São Paulo", "Paulistas da família: ônibus pros shows e encontro antes do Carnaval na Cidade.", "Thiago Lima"),
    ("Fã-clube BA", "Salvador", "Salvador na Virada e onde mais a Lud for.", "Duda Ribeiro"),
    ("Fã-clube MG", "Belo Horizonte", "Domingo é dia de Numanice no talo.", "Carol Martins"),
]
POSTS_OFICIAIS = [
    "Bi Festinha chegou: o primeiro single do EP Fervo da Lud, com Puterrier e HITMAKER. O FunkMilla tá de volta e é pra tocar alto.",
    "\"O Numanice começou como um sonho e virou um movimento.\"",
    "Manda o vídeo do teu melhor momento num Numanice. Os mais bonitos entram no Mural da família.",
    "Coleção de óculos Chilli Beans x Ludmilla na Loja: quadrado caramelo, cat rosé e mais.",
    "Datas novas na agenda: Repique, Virada, Spotify Superfans Experience e CarnaRildy. Anota aí e chama a galera.",
    "Roleta da Lud girando: ingresso, front stage, óculos e pôster para quem tiver sorte.",
]
POSTS_FAS = [
    "Ingresso do CarnaRildy garantido antes de esgotar. Quem é do fã-clube RJ, bora marcar o ponto na Marina da Glória.",
    "Bi Festinha no repeat desde quinta. O FunkMilla voltou e eu não tô bem.",
    "Alguém já sabe o horário da Lud no Festival da Virada? Salvador inteira vai tá lá no dia 2.",
    "Domingo sem Numanice #2 no talo não é domingo. O pagodinho virou religião mesmo.",
    "Óculos da coleção chegou! Quadrado caramelo com a assinatura dela na haste.",
    "Pôr do sol em Ipanema e Numanice no fone. Não tem como ser mais carioca que isso.",
    "Caravana Ludmillers SP pro Carnaval na Cidade: 2 ônibus já lotados, abrimos o terceiro.",
    "Fiz o cartaz pro Repique. Será que ela lê?",
    "Primeira vez na grade num show dela. A proximidade que ela fala é real, gente.",
    "Repostando porque isso aqui é a cara do Numanice.",
]
COMENTARIOS = ["Também vou!", "Que demais", "Bora!", "Mandou bem", "Quero ir junto", "Numanice!", "Fechou", "Chama a família"]
# cidade, casa, endereço, data, horário, abertura dos portões, classificação, status, ingresso (nome, url)
SHOWS = [
    ("Ribeirão Preto", "Festival Repique · Estádio do Comercial", "Estádio do Comercial, Ribeirão Preto - SP", date(2026, 12, 5), "22h", "18h", "18+", "last_batches", "Ingresse", "https://www.ingresse.com/"),
    ("Salvador", "Festival da Virada · Arena O Canto da Cidade", "Arena O Canto da Cidade, Salvador - BA", date(2027, 1, 2), "21h", "16h", "Livre", "on_sale", "", ""),
    ("São Paulo", "Spotify Superfans Experience · Distrito Anhembi", "Distrito Anhembi, São Paulo - SP", date(2027, 1, 23), "20h", "17h", "16+", "on_sale", "Mundo Ticket", "https://www.mundoticket.com.br/"),
    ("São Paulo", "Carnaval na Cidade · local a confirmar", "Local a confirmar, São Paulo - SP", date(2027, 2, 7), "16h", "14h", "18+", "soon", "Ingresse", "https://www.ingresse.com/"),
    ("Rio de Janeiro", "CarnaRildy · Axia Marina da Glória", "Axia Marina da Glória, Rio de Janeiro - RJ", date(2027, 2, 13), "18h", "15h", "18+", "last_batches", "Ingresse", "https://www.ingresse.com/"),
]
AGENCIAS = [("Caravana Lud", "(11) 99999-2001", "https://caravanalud.example"), ("Rota Show Turismo", "contato@rotashow.example", "https://rotashow.example"), ("Night Express Transfer", "(21) 98888-3002", "https://nightexpress.example")]
EXPERIENCIAS = [("transfer", 9000), ("jantar", 48000), ("camarim", 65000), ("pre", 12000), ("after", 18000), ("hotel", 39000)]
# Coleção Chilli Beans x Ludmilla (mesmos produtos do mock; óculos de acetato R$ 219,99 e de metal R$ 274,99)
PRODUTOS = [
    ("Quadrado Caramelo", "acessorios", 21999, "#F8E8D8", 40, "/media/ludmilla/oc-cl-4926.jpg"),
    ("Cat Rosé", "acessorios", 21999, "#F8E8D8", 40, "/media/ludmilla/oc-cl-3825.jpg"),
    ("Quadrado Preto Dourado", "acessorios", 21999, "#F8E8D8", 40, "/media/ludmilla/oc-cl-4945.jpg"),
    ("Bossa Nova Preto", "acessorios", 21999, "#F8E8D8", 0, "/media/ludmilla/oc-cl-4944.jpg"),
    ("Retangular Rosado", "acessorios", 21999, "#F8E8D8", 40, "/media/ludmilla/oc-cl-4947.jpg"),
    ("Cat Marrom", "acessorios", 21999, "#F8E8D8", 40, "/media/ludmilla/oc-cl-4950.jpg"),
    ("Cat Dourado", "acessorios", 27499, "#F8E8D8", 30, "/media/ludmilla/oc-mt-4156.jpg"),
    ("Quadrado Dourado", "acessorios", 27499, "#F8E8D8", 30, "/media/ludmilla/oc-mt-4251.jpg"),
    ("Redondo Grafite", "acessorios", 27499, "#F8E8D8", 30, "/media/ludmilla/oc-mt-4159.jpg"),
    ("Sem Aro Lilás", "acessorios", 27499, "#F8E8D8", 30, "/media/ludmilla/oc-mt-4150.jpg"),
    ("Flat-top Marrom", "acessorios", 27499, "#F8E8D8", 30, "/media/ludmilla/oc-mt-4161.jpg"),
]
FAIXAS = [
    ("Bi Festinha", "Single · Fervo da Lud · esta semana", "05/11/2026", 18420),
    ("Fragmentos · A Experiência", "Ao vivo · Qualistage", "2026", 12730),
    ("Numanice #3 (Ao Vivo)", "Ao vivo", "2024", 9904),
    ("Numanice #2", "Álbum", "2022", 8611),
]
BENEFICIOS = [
    ("Drop News exclusivos", "Bastidores e novidades só para membros"),
    ("Prioridade na sorte dos eventos", "Mais chances nos brindes de cada show"),
    ("Desconto na Loja Ludmilla", "10% em todos os óculos"),
    ("Drops Hits antes de todo mundo", "Prévias liberadas primeiro para você"),
    ("Selo de membro no mural", "Seu perfil com a marca do fã clube"),
    ("Giros extras no PicKup", "+5 giros todo mês"),
]
CARONAS = [
    # cidade de saída, ponto de encontro, carro, vagas, preço por vaga (centavos), observação
    ("Campinas", "Posto Shell, Av. John Boyd Dunlop", "Honda Civic prata", 4, 4500, "Saída 17h, volta depois do show."),
    ("Santos", "Terminal Rodoviário", "Hyundai HB20 preto", 4, 6000, "Chegamos 2 horas antes dos portões."),
    ("Niterói", "Barcas, Praça Arariboia", "Chevrolet Onix azul", 4, 3500, "Combinamos o retorno pelo chat."),
    ("Petrópolis", "Rodoviária de Petrópolis", "Renault Kwid vermelho", 3, 5000, ""),
    ("Juiz de Fora", "Posto BR, BR-040", "Toyota Corolla preto", 4, 7000, "Parada rápida para abastecer."),
    ("Sorocaba", "Terminal Rodoviário", "VW Polo cinza", 3, 6500, "Numanice tocando no caminho inteiro."),
    ("Campos dos Goytacazes", "Posto Ipiranga, BR-101", "Ford Ka branco", 3, 4000, ""),
    ("Uberlândia", "Terminal Rodoviário", "Fiat Argo branco", 4, 8500, "Ar-condicionado e carregador de celular."),
    ("Franca", "Posto Shell, Rodovia Cândido Portinari", "Jeep Renegade verde", 4, 9000, "Levamos malas pequenas."),
]
# situação das reservas de cada viagem: (vagas, situação, forma de pagamento)
RESERVAS = [
    [(1, B_PAID, "pix"), (2, B_PAID, "cartao"), (1, B_RESERVED, "")],
    [(2, B_PAID, "pix"), (1, B_REFUNDED, "cartao"), (1, B_CANCELLED, "")],
    [(1, B_PAID, "pix"), (1, B_PAID, "cartao")],
    [(1, B_PAID, "cartao")],
    [(2, B_PAID, "pix"), (1, B_PAID, "pix")],
    [(1, B_PAID, "cartao"), (1, B_PAID, "pix")],
    [(1, B_PAID, "pix")],
    [(1, B_PAID, "cartao"), (2, B_PAID, "pix")],
    [],
]

# roleta do mock: Ingresso, Óculos da Lud, Front stage, Cupom 15%, Pôster, Tente de novo, Abadá, Pré-escuta
RETIRADA = "Retire na lojinha da Ludmilla, no show, com este código e um documento com foto."
PREMIOS = [
    ("Ingresso", "ticket", 0, None, "Ingresso unitário (1 pessoa). Retire na bilheteria do próximo show com este código e um documento com foto."),
    ("Óculos da Lud", "pickup", 0, 100, RETIRADA),
    ("Front stage", "pickup", 0, 50, "Acesso ao front stage. Retire a pulseira na entrada do show, com este código e um documento com foto."),
    ("Cupom 15%", "coupon", 15, 1000, ""),
    ("Pôster", "pickup", 0, 300, RETIRADA),
    ("Tente de novo", "none", 0, None, ""),
    ("Abadá", "pickup", 0, 200, RETIRADA),
    ("Pré-escuta", "none", 0, None, ""),
]


def vazio(db, modelo, *conds) -> bool:
    return not db.scalar(select(func.count()).select_from(modelo).where(*conds))


with SessionLocal() as db:
    art = db.scalar(select(m.Artist).where(m.Artist.slug == SLUG))
    if not art:
        raise SystemExit("Ambiente ludmilla não encontrado: rode antes o criar_ludmilla.py.")
    if not art.fan_club_name.strip():
        art.fan_club_name = "Fã-clube oficial Ludmilla"
    oficial = next((c for c in art.clubs if c.is_master), None)
    if not oficial:
        raise SystemExit("A Ludmilla não tem fã clube oficial.")

    # ---------------------------------------------------------------- fã clubes e donos
    senhas = []
    clubes = [oficial]
    for nome, cidade, desc, dono in CLUBES:
        c = db.scalar(select(m.FanClub).where(m.FanClub.artist_id == art.id, m.FanClub.name == nome))
        if not c:
            c = create_club(db, art, nome, desc, cidade)
            email = f"dono.{c.slug}@ludmilla.example"
            u = db.scalar(select(m.User).where(m.User.email == email))
            if not u:
                senha = temp_password()
                u = m.User(email=email, name=dono, handle="@" + dono.lower().replace(" ", "."), role=m.ROLE_ARTIST_ADMIN, password_hash=hash_password(senha), city=cidade)
                db.add(u)
                db.flush()
                senhas.append((nome, email, senha))
            db.add(m.ClubStaff(club_id=c.id, user_id=u.id, role=m.STAFF_OWNER, role_label="Dono do fã clube"))
            print(f"fã clube criado: {nome}")
        clubes.append(c)
    db.flush()

    # ---------------------------------------------------------------- fãs, membros e assinantes
    fas = list(db.scalars(select(m.User).where(m.User.role == m.ROLE_FAN).order_by(m.User.created_at)))[:40]
    fandoms = {f.user_id: f for f in db.scalars(select(m.Fandom).where(m.Fandom.artist_id == art.id))}
    novos = 0
    for i, u in enumerate(fas):
        f = fandoms.get(u.id)
        if not f:
            f = m.Fandom(artist_id=art.id, user_id=u.id, luck_points=rnd.randint(0, 40), spins=rnd.randint(1, 5))
            db.add(f)
            fandoms[u.id] = f
            novos += 1
            if i < 14:
                f.member_status = "active"
                f.member_since = date.today() - timedelta(days=rnd.randint(2, 85))
                f.payment = "Pix" if i % 2 == 0 else "Cartão"
            elif i < 16:
                f.member_status = "pending"
            elif i == 16:
                f.member_status = "canceled"
                f.member_since = date.today() - timedelta(days=60)
    db.flush()
    ja = {(cm.club_id, cm.user_id) for cm in db.scalars(select(m.ClubMember).where(m.ClubMember.club_id.in_([c.id for c in clubes])))}
    membros = 0
    for i, u in enumerate(fas):
        alvo = [oficial, clubes[1 + i % (len(clubes) - 1)]]
        for c in alvo:
            if (c.id, u.id) not in ja:
                db.add(m.ClubMember(club_id=c.id, user_id=u.id, created_at=agora - timedelta(days=rnd.randint(1, 80))))
                ja.add((c.id, u.id))
                membros += 1
    print(f"fãs na Ludmilla: {novos} novos; {membros} entradas em fã clubes")

    # ---------------------------------------------------------------- feed
    if vazio(db, m.Post, m.Post.artist_id == art.id):
        for i, txt in enumerate(POSTS_OFICIAIS):
            db.add(m.Post(artist_id=art.id, kind="drop", official=True, text=txt, likes=rnd.randint(40, 380), comments=0, reposts=rnd.randint(2, 40), views=rnd.randint(500, 4000), created_at=agora - timedelta(days=i * 3 + 1, hours=i)))
        db.flush()
        por_clube: dict[str, list] = {}
        for c in clubes:
            por_clube[c.id] = [cm.user_id for cm in db.scalars(select(m.ClubMember).where(m.ClubMember.club_id == c.id))]
        n = 0
        for c in clubes:
            autores = por_clube[c.id]
            for j in range(4 if not c.is_master else 6):
                if not autores:
                    break
                p = m.Post(
                    artist_id=art.id, kind="galera", club_id=c.id, author_id=rnd.choice(autores), official=False, text=POSTS_FAS[(n + j) % len(POSTS_FAS)],
                    likes=rnd.randint(2, 90), comments=0, reposts=rnd.randint(0, 9), views=rnd.randint(40, 600), created_at=agora - timedelta(days=rnd.randint(0, 20), hours=rnd.randint(0, 20)),
                )
                db.add(p)
                n += 1
        db.flush()
        for p in db.scalars(select(m.Post).where(m.Post.artist_id == art.id)):
            quem = [cm.user_id for cm in db.scalars(select(m.ClubMember).where(m.ClubMember.club_id == (p.club_id or oficial.id)))] or [fas[0].id]
            k = rnd.randint(0, 3)
            for _ in range(k):
                db.add(m.PostComment(post_id=p.id, author_id=rnd.choice(quem), text=rnd.choice(COMENTARIOS), created_at=p.created_at + timedelta(minutes=rnd.randint(5, 600))))
            p.comments = k
        print(f"feed: {len(POSTS_OFICIAIS)} posts oficiais e {n} posts dos fãs (sem imagens)")

    # ---------------------------------------------------------------- shows, agências e pacotes
    if vazio(db, m.Event, m.Event.artist_id == art.id):
        ags = []
        for nome, contato, url in AGENCIAS:
            ag = db.scalar(select(m.Agency).where(m.Agency.artist_id == art.id, m.Agency.name == nome))
            if not ag:
                ag = m.Agency(artist_id=art.id, name=nome, contact=contato, url=url, active=True)
                db.add(ag)
            ags.append(ag)
        db.flush()
        for i, (cidade, casa, end, dia, hora, portoes, idade, status, bilheteria, link) in enumerate(SHOWS):
            ev = m.Event(
                artist_id=art.id, date=dia, city=cidade, venue=casa, time=hora, address=end, doors_open=portoes, age_rating=idade,
                lineup="Ludmilla e convidados", status=status, ticketing_name=bilheteria, ticketing_url=link,
            )
            db.add(ev)
            db.flush()
            if link:
                db.add(m.Vendor(artist_id=art.id, event_id=ev.id, name=f"{bilheteria} (oficial)", type="Ingresso", tag="Oficial", price_label="a partir de R$ 120", url=link, position=0))
            db.add(m.Gift(artist_id=art.id, event_id=ev.id, name="Pulseira Ludmilla", phase="before", qty_label="500 un.", position=0))
            db.add(m.Gift(artist_id=art.id, event_id=ev.id, name="Pôster autografado", phase="after", qty_label="3 un.", position=1))
            ag = ags[i % len(ags)]
            db.add(
                m.EventPackage(
                    artist_id=art.id, event_id=ev.id, agency_id=ag.id, name=f"Experiências · {cidade}", description="Transfer, jantar, camarim, pré-esquenta, after e hotel: leve só o que quiser.",
                    transfer_details=f"Saída 4h antes do show, retorno 1h após o encerramento ({cidade}).", url=f"{ag.url}/ludmilla/{i}", items=[],
                    addons=[{"key": k, "price_cents": p, "sold_out": k == "camarim" and i == 0} for k, p in EXPERIENCIAS], active=True, position=0,
                )
            )
        db.flush()
        print(f"shows: {len(SHOWS)} (com ingresso, brindes e pacotes das agências)")

    # compras de experiências (lista de compradores e receita do show)
    eventos = list(db.scalars(select(m.Event).where(m.Event.artist_id == art.id).order_by(m.Event.date)))
    if eventos and vazio(db, m.TicketPurchase, m.TicketPurchase.artist_id == art.id):
        nomes = dict(EXPERIENCIAS)
        for i, u in enumerate(fas[:18]):
            ev = eventos[i % len(eventos)]
            ag = AGENCIAS[i % len(AGENCIAS)][0]
            chaves = rnd.sample(list(nomes), rnd.randint(1, 3))
            rot = {"transfer": "Transfer ida e volta", "jantar": "Jantar com a Ludmilla", "camarim": "Meet & greet no camarim", "pre": "Pré-esquenta", "after": "After", "hotel": "Hotel com hospedagem"}
            db.add(
                m.TicketPurchase(
                    artist_id=art.id, user_id=u.id, event_id=ev.id, package_name=f"Experiências · {ev.city}", agency_name=ag, label=" + ".join(rot[k] for k in chaves),
                    kind="experience", addons=chaves, price_cents=sum(nomes[k] for k in chaves), ticket_optin_at=agora - timedelta(days=rnd.randint(1, 20)),
                    created_at=agora - timedelta(days=rnd.randint(1, 20), hours=rnd.randint(0, 20)),
                )
            )
        print("compras de experiências: 18")

    # ---------------------------------------------------------------- loja
    if vazio(db, m.Product, m.Product.artist_id == art.id):
        prods = []
        for i, (nome, cat, preco, cor, estoque, foto) in enumerate(PRODUTOS):
            p = m.Product(artist_id=art.id, name=nome, category=cat, price_cents=preco, color=cor, position=i, stock=estoque, image_path=foto)
            db.add(p)
            prods.append(p)
        db.flush()
        vendaveis = [p for p in prods if p.stock]
        for i, u in enumerate(fas[:12]):
            p = vendaveis[i % len(vendaveis)]
            qtd = rnd.randint(1, 2)
            retirada = i % 3 != 0
            sub = p.price_cents * qtd
            frete = 0 if retirada or sub >= 30000 else 1990
            o = m.StoreOrder(artist_id=art.id, user_id=u.id, code=f"LJ-{rnd.randint(10000, 99999)}", delivery="pickup" if retirada else "ship", address="" if retirada else "Rua das Flores, 100, São Paulo",
                             subtotal_cents=sub, shipping_cents=frete, total_cents=sub + frete, created_at=agora - timedelta(days=rnd.randint(1, 25), hours=rnd.randint(0, 20)))
            db.add(o)
            db.flush()
            db.add(m.ProductPurchase(artist_id=art.id, user_id=u.id, product_id=p.id, name=p.name, category=p.category, price_cents=p.price_cents, qty=qtd, size="", order_id=o.id, created_at=o.created_at))
            if p.stock is not None:
                p.stock = max(0, p.stock - qtd)
        for u in fas[:30]:  # visitas e carrinhos para o funil da loja
            for p in rnd.sample(prods, rnd.randint(1, 4)):
                t = agora - timedelta(days=rnd.randint(0, 25), hours=rnd.randint(0, 20))
                db.add(m.StoreEvent(artist_id=art.id, user_id=u.id, product_id=p.id, kind="view", created_at=t))
                if rnd.random() < 0.45:
                    db.add(m.StoreEvent(artist_id=art.id, user_id=u.id, product_id=p.id, kind="cart_add", created_at=t + timedelta(minutes=2)))
        print(f"loja: {len(PRODUTOS)} produtos (1 esgotado), 12 pedidos e visitas/carrinhos")

    # ---------------------------------------------------------------- Drops Hits, benefícios
    if vazio(db, m.Track, m.Track.artist_id == art.id):
        for i, (t, meta, lanc, votos) in enumerate(FAIXAS):
            db.add(m.Track(artist_id=art.id, title=t, meta=meta, release_label=lanc, duration_sec=30, votes=votos, views=rnd.randint(200, 2500), position=i))
        print(f"drops: {len(FAIXAS)} faixas")
    if vazio(db, m.MemberPerk, m.MemberPerk.artist_id == art.id):
        for i, (t, s) in enumerate(BENEFICIOS):
            db.add(m.MemberPerk(artist_id=art.id, title=t, sub=s, position=i))
        print("benefícios dos membros: 6")

    # ---------------------------------------------------------------- roleta (prêmios, giros e ganhadores)
    if vazio(db, m.Prize, m.Prize.artist_id == art.id):
        pr = []
        for i, (rot, kind, pct, estoque, instr) in enumerate(PREMIOS):
            p = m.Prize(artist_id=art.id, club_id=oficial.id, label=rot, is_retry=rot == "Tente de novo", points=0 if kind == "none" else 10, position=i, kind=kind, percent=pct, instructions=instr, stock=estoque)
            db.add(p)
            pr.append(p)
        db.flush()
        for i, u in enumerate(fas[:14]):
            p = pr[(i * 3) % len(pr)]
            t = agora - timedelta(days=rnd.randint(0, 18), hours=rnd.randint(0, 20))
            db.add(m.SpinCredit(artist_id=art.id, user_id=u.id, reason="Bônus de boas-vindas", used_at=t, prize_label=p.label, club_id=oficial.id, prize_id=p.id, created_at=t - timedelta(hours=1)))
            if p.kind != "none":
                db.add(m.Reward(artist_id=art.id, club_id=oficial.id, user_id=u.id, label=p.label, kind=p.kind, code="".join(rnd.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(5)),
                                instructions=p.instructions, coupon_code="", prize_id=p.id, expires_on=date.today() + timedelta(days=60), created_at=t))
                if p.stock is not None:
                    p.stock = max(0, p.stock - 1)
        print(f"roleta: {len(PREMIOS)} prêmios, 14 giros e ganhadores")

    # ---------------------------------------------------------------- ranking (compartilhamentos confirmados)
    if vazio(db, m.InstagramShare, m.InstagramShare.artist_id == art.id):
        oficiais = list(db.scalars(select(m.Post).where(m.Post.artist_id == art.id, m.Post.official.is_(True))))
        n = 0
        for i, u in enumerate(fas[:20]):
            for _ in range(rnd.randint(1, 4)):
                p = rnd.choice(oficiais) if oficiais else None
                t = agora - timedelta(days=rnd.randint(0, 25), hours=rnd.randint(0, 20))
                db.add(m.InstagramShare(artist_id=art.id, user_id=u.id, post_id=p.id if p else None, status="verified", media_id=f"lud-{u.id[:6]}-{n}", permalink="https://instagram.com/p/exemplo", created_at=t, verified_at=t))
                n += 1
        print(f"ranking: {n} compartilhamentos confirmados")

    # ---------------------------------------------------------------- caronas por show
    if eventos and vazio(db, Ride, Ride.artist_id == art.id) and len(fas) >= 20:
        motoristas, passageiros = fas[20:29], fas[0:20]
        criadas = 0
        for i, (origem, ponto, carro, vagas, preco, obs) in enumerate(CARONAS):
            ev = eventos[i % len(eventos)]
            saida = datetime(ev.date.year, ev.date.month, ev.date.day, 14, tzinfo=timezone.utc) - timedelta(days=1)
            r = Ride(
                artist_id=art.id, event_id=ev.id, driver_id=motoristas[i % len(motoristas)].id, origin_city=origem, meeting_point=ponto, depart_at=saida, seats_total=vagas,
                price_cents=preco, car=carro, notes=obs, status=R_CANCELLED if i == 3 else R_OPEN, created_at=agora - timedelta(days=2 + i),
            )
            db.add(r)
            db.flush()
            criadas += 1
            for j, (qtd, sit, metodo) in enumerate(RESERVAS[i]):
                quem = passageiros[(i * 3 + j) % len(passageiros)]
                quando = agora - timedelta(days=1, hours=i + 2 * j)
                pago = sit in (B_PAID, B_REFUNDED)
                b = RideBooking(
                    ride_id=r.id, passenger_id=quem.id, seats=qtd, amount_cents=qtd * preco, status=sit, expires_at=agora + timedelta(minutes=12) if sit == B_RESERVED else None,
                    payment_method=metodo, paid_at=quando + timedelta(minutes=3) if pago else None, created_at=quando,
                )
                db.add(b)
                db.flush()
                if pago:
                    db.add(RideLedger(booking_id=b.id, kind="hold", amount_cents=b.amount_cents, note="Pagamento retido até a viagem", created_at=b.paid_at))
                if sit == B_REFUNDED:
                    db.add(RideLedger(booking_id=b.id, kind="refund", amount_cents=b.amount_cents, note="Devolvido ao passageiro", created_at=b.paid_at + timedelta(hours=6)))
        print(f"caronas: {criadas} viagens com reservas")

    db.commit()

if senhas:
    print("\nDonos dos fã clubes criados (anote as senhas, elas não aparecem de novo):")
    for nome, email, senha in senhas:
        print(f"  {nome:<26} {email:<40} {senha}")
print("\npronto")
