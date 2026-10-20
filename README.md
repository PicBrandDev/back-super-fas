# Super Fãs — Back (FastAPI)

API dos fã clubes. Atende o front [front-super-fas](../front-super-fas).

Cada cantor tem um ambiente com até 10 fã clubes (1 master + 9). A equipe do fã clube master administra
o ambiente (conteúdo oficial e os outros fã clubes); cada fã clube tem 1 dono + ajudantes, membros,
mural da galera, PicKap e vitrines de anúncio próprios. A assinatura de membro é do ambiente.

Stack: **FastAPI · SQLAlchemy 2 · PostgreSQL** (SQLite no desenvolvimento) · login com JWT.

## Rodando local

```bash
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt     # Windows: .venv\Scripts\pip
.venv/bin/uvicorn app.main:app --reload           # http://localhost:8000/docs
```

Sem `DATABASE_URL` usa um arquivo `superfas.db` (SQLite). Para o front usar esta API, no `.env.local` do front:
`API_URL=http://localhost:8000` e `JWT_SECRET` igual ao daqui (sem `.env`, o valor de desenvolvimento é o padrão de `app/config.py`).

Testes: `.venv/bin/python -m pytest`

## Primeira subida

Com o banco vazio, a API cria o ambiente **Vintage Culture** (com as 6 vitrines do ambiente e o fã clube master) e uma conta de teste de cada tipo:

| Tipo | E-mail |
| --- | --- |
| Admin master | admin@superfas.dev |
| Dono do fã clube master do Vintage Culture (admin master do cantor) | vintage@superfas.dev |
| Patrocinador | marca@superfas.dev |
| Fã | fa@superfas.dev |

A senha é a de `SEED_PASSWORD` (ou uma aleatória, mostrada no log). O resto do conteúdo (shows, posts, produtos…) é criado pelas telas de admin.

## Rotas

Documentação interativa em `/docs`. Resumo:

**Login** — `POST /auth/login`, `POST /auth/register` (só fã), `GET /auth/me`, `POST /auth/change-password`

**Área do fã** (qualquer conta logada)
- `GET /artists`, `GET /artists/{slug}`, `GET /me?artist=`, `GET /me/fandoms`
- `GET|POST /artists/{slug}/posts` (fã posta em `galera` ou `instagram`)
- `GET /artists/{slug}/events`, `/events/{id}`, `/events/{id}/vendors`, `/events/{id}/gifts`, `POST /events/{id}/luck/join`
- `GET /artists/{slug}/pickap/prizes`, `POST /artists/{slug}/pickap/spin` (o servidor sorteia)
- `GET /artists/{slug}/products`, `/tracks`, `/ads/home`, `/ad-slots`, `/membership/perks`
- `POST /artists/{slug}/membership/subscribe` (assinatura simulada, sem cobrança)

**Fã clubes** (qualquer conta logada vê; a equipe administra)
- `GET /artists/{slug}/clubs`, `GET /artists/{slug}/clubs/{club}`, `POST .../join`, `POST .../leave`
- Mural: `GET|POST /artists/{slug}/clubs/{club}/posts` (só membro posta)
- PicKap: `GET .../pickap/prizes`, `POST .../pickap/spin`
- Anúncios: `GET .../ad-slots`, `GET .../ads/home`, `GET .../campaigns` (equipe)
- Equipe: `GET|POST .../staff`, `DELETE .../staff/{id}` (dono: o ambiente escolhe; ajudantes: o dono convida; até 10)
- Membros: `GET .../members`, `DELETE .../members/{userId}`
- Conteúdo do clube: `GET|POST|PATCH|DELETE .../manage/prizes`, `GET|DELETE .../manage/posts`
- Criar/editar/apagar: `POST /artists/{slug}/clubs` (dono do master), `PATCH|DELETE /artists/{slug}/clubs/{club}`
- `GET /me/staff` — onde a pessoa está na equipe

**Administração do ambiente** (equipe do fã clube master ou admin da plataforma)
- Conteúdo oficial: `GET|POST /artists/{slug}/manage/{recurso}` e `PATCH|DELETE /artists/{slug}/manage/{recurso}/{id}`
  com recurso = `events`, `vendors`, `gifts`, `posts`, `products`, `tracks`, `perks`
- Assinantes: `GET /artists/{slug}/members`, `POST /members/{id}/charge`, `POST /members/{id}/cancel`
- Anúncios do ambiente: `GET /artists/{slug}/campaigns`, `PATCH /artists/{slug}/ad-slots/{key}`
- Aprovar campanha: `POST /campaigns/{id}/approve|reject` (quem administra a vitrine: ambiente ou fã clube)

**Admin da plataforma**
- `POST /admin/fan-clubs` (cria o ambiente de um cantor já com o fã clube master; o 1º convidado é o dono), `PATCH|DELETE /admin/fan-clubs/{slug}`
- `GET /admin/campaigns` (todas)
- `GET /admin/sponsors`, `POST /admin/sponsors/invite`

**Patrocinador** — `GET /sponsor/me`, `GET /sponsor/campaigns`, `POST /sponsor/campaigns` (multipart, arte JPG/PNG opcional)

Convites (admin de fã clube e patrocinador) criam a conta com **senha provisória**, devolvida uma vez na resposta. Ainda não há envio de e-mail.

## Estrutura

```
app/
  main.py        app, rotas e primeira carga
  config.py      variáveis de ambiente
  models.py      tabelas
  schemas.py     entrada/saída (camelCase, igual a src/lib/types.ts do front)
  security.py    senha (argon2), JWT e permissões
  seed.py        dados iniciais
  defaults.py    temas e vitrines padrão
  migrations.py  atualiza o banco na subida (sem apagar dados)
  routers/       auth, fan (área do fã), clubs (fã clubes), club_admin (ambiente), master (plataforma), sponsor
tests/           testes da API (pytest)
```

## Atualizações do banco

`app/migrations.py` roda na subida: cria tabelas novas, acrescenta colunas e converte dados antigos
(ex.: cria o fã clube master de cada cantor e passa a equipe antiga para ele). Não apaga nada.

## Próximos passos

- Trocar `migrations.py` por Alembic quando o esquema começar a mudar com frequência.
- Envio de e-mail nos convites, pagamento real da assinatura, busca do Photo Finder.
