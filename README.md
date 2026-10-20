# Super Fãs — Back (FastAPI)

API dos fã clubes. Atende o front [front-super-fas](../front-super-fas).

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

Com o banco vazio, a API cria o fã clube **Vintage Culture** (com as 6 vitrines de anúncio) e uma conta de teste de cada tipo:

| Tipo | E-mail |
| --- | --- |
| Admin master | admin@superfas.dev |
| Admin do fã clube (Vintage Culture) | vintage@superfas.dev |
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

**Admin do fã clube** (admin daquele fã clube ou master)
- Conteúdo: `GET|POST /artists/{slug}/manage/{recurso}` e `PATCH|DELETE /artists/{slug}/manage/{recurso}/{id}`
  com recurso = `events`, `vendors`, `gifts`, `posts`, `prizes`, `products`, `tracks`, `perks`
- Membros: `GET /artists/{slug}/members`, `POST /members/{id}/charge`, `POST /members/{id}/cancel`
- Equipe: `GET|POST /artists/{slug}/admins`, `DELETE /artists/{slug}/admins/{id}` (até 10)

**Admin master**
- `POST /admin/fan-clubs`, `PATCH|DELETE /admin/fan-clubs/{slug}`
- `PATCH /artists/{slug}/ad-slots/{key}` (ligar/pausar vitrine, preço)
- `GET /admin/campaigns`, `POST /admin/campaigns/{id}/approve|reject`
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
  routers/       auth, fan, club_admin, master, sponsor
tests/           testes da API (pytest)
```

## Próximos passos

- Migrações com Alembic (hoje as tabelas são criadas na subida; mudar uma coluna exige recriar o banco).
- Envio de e-mail nos convites, pagamento real da assinatura, busca do Photo Finder.
