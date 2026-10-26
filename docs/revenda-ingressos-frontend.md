# Revenda de ingressos — guia para o front-end

> Branch do back: `feature/marketplace-ingressos`. Este documento é o contrato da API de revenda entre fãs, com pagamento retido (escrow). A estilização fica com o dev de front: pode ser simples e funcional, já usando as cores e fontes do app.

## 1. O que é

Quando um show **esgota na ticketeira oficial**, o admin do ambiente (Vintage) **libera a revenda** daquele show. A partir daí, fãs podem **anunciar ingressos** que têm e outros fãs podem **comprá-los dentro do app**, com o dinheiro **retido pela plataforma** até o comprador confirmar que recebeu o ingresso.

Ideia da tela: parece um feed de posts, mas antes o fã escolhe o **show** em um **hub**.

Regras que o front precisa comunicar bem:

| Regra | Valor |
|---|---|
| Quem libera a revenda de um show | só o admin do ambiente (duas chaves: "esgotou na ticketeira" + "revenda aberta") |
| Preço máximo por ingresso | **valor de face** do tipo de ingresso (a API recusa acima) |
| Compra | por ingresso, **compra parcial** (de 1 até o saldo do lote) |
| Reserva até pagar | **15 minutos** |
| Vendedor transfere o ingresso na ticketeira | até **24h** depois do pagamento ou até **2h antes do show** (o que vier antes) |
| Comprador confirma o recebimento | até **48h** depois do vendedor avisar que transferiu; sem resposta, o valor é liberado ao vendedor |
| Disputa | o comprador abre antes do prazo; o admin decide (reembolsar ou liberar) |
| Compra bloqueada | a menos de **4h** do show |
| Taxa | % configurável pelo admin, descontada do **vendedor** (o comprador paga o preço anunciado) |
| Quem pode comprar | fã (ou dono de fã clube) que entrou no ambiente e tem **endereço completo** no cadastro |
| Quem pode vender | o mesmo, mais **CPF e telefone** informados |

## 2. Convenções da API

- Base: `/artists/{slug}/resale/...` (ex.: `/artists/vintage-culture/resale/events`). Identidade do usuário é global: `/me/identity`.
- Autenticação: igual ao resto do app (cookie `sf_session` → `Authorization: Bearer`). Usar as server actions de `src/app/actions/*` (`send`/`fetchJson`).
- JSON em **camelCase**. Valores em **centavos inteiros** (`unitPriceCents: 18000` = R$ 180,00). Datas ISO 8601 em UTC (`2031-09-12T01:00:00Z`); o show tem `date` (`YYYY-MM-DD`) e `time` (texto livre, ex. `"22h"`).
- **Erros**: sempre `{ "detail": "mensagem em português", "code": "CODIGO_EM_MAQUINA" }`. Mostre o `detail` ao usuário e use o `code` para decidir o que fazer (tabela na seção 8). Erros de validação de formato (422) vêm no padrão do FastAPI (`detail` é uma lista).
- **Idempotência**: ao reservar, envie o header `Idempotency-Key` (uuid de 8 a 80 caracteres), **gerado uma vez por tentativa de compra** e reutilizado se a requisição for repetida (duplo clique, rede ruim). A API devolve o mesmo pedido.
- **Ações repetidas** (pagar, confirmar, cancelar, "já transferi") são seguras: se o pedido já está no estado final daquela ação, a API devolve `200` com o estado atual.
- **Tempo real**: não há websocket. Faça *polling* leve (a cada 10–20 s) na tela do pedido; os prazos vencidos são aplicados pela própria API ao você ler.
- **Flags de ação**: o `OrderOut` traz `canPay`, `canCancel`, `canMarkTransferred`, `canConfirm`, `canDispute`, `canReplyDispute`, `canReview`. **Mostre os botões só quando a flag for `true`** (não reimplemente a regra no front).

## 3. Telas sugeridas (todas simples)

Rotas sugeridas no front (`src/app/[artista]/(fan)/revenda/...`):

| Rota | Tela | Endpoints |
|---|---|---|
| `/revenda` | **Hub**: lista de shows com revenda liberada (cidade, data, "N anúncios", "a partir de R$ X") | `GET /events`, `GET /me/eligibility` |
| `/revenda/[eventoId]` | **Show**: abas por tipo de ingresso + lista de anúncios (ordenar por preço/recentes), aviso do teto de preço | `GET /events/{id}`, `GET /events/{id}/listings` |
| `/revenda/anuncio/[id]` | **Anúncio**: lote, preço, **cartão de confiança do vendedor**, escolha da quantidade, "Reservar" | `GET /listings/{id}`, `POST /listings/{id}/orders` |
| `/revenda/vender/[eventoId]` | **Vender**: tipo, quantidade, preço por ingresso, **um código por ingresso**, upload da prova | `POST /events/{id}/listings` (multipart) |
| `/revenda/meus-anuncios` | Meus anúncios (status, motivo da rejeição, reenviar, cancelar) | `GET /me/listings`, `POST /listings/{id}/cancel|resubmit` |
| `/revenda/pedidos` | Meus pedidos (comprando e vendendo) | `GET /me/orders?role=` |
| `/revenda/pedidos/[id]` | **Pedido**: linha do tempo, prazos, botões (pagar, transferi, confirmar, disputa, avaliar) | `GET /orders/{id}` + ações |
| `/revenda/vendedor/[userId]` | Perfil do vendedor + avaliações | `GET /sellers/{id}`, `GET /sellers/{id}/reviews` |
| `/revenda/identidade` | Informar CPF e telefone (necessário para vender) | `GET/PUT /me/identity` |
| `/admin/revenda` | Admin: chaves por show, taxa, fila de provas, disputas, pedidos, livro-razão | seção 7 |

Endereço incompleto (`missing: ["address"]`): `PUT /auth/address` `{ zipCode, street, number, complement, neighborhood, city, state }` → `ProfileOut`.

**Antes de vender ou comprar**, chame `GET /me/eligibility`: `{ canBuy, canSell, missing }`. `missing` pode conter `role` (conta sem permissão), `fandom` (não entrou no ambiente), `address` (completar endereço no perfil), `cpf`, `phone`. Leve o usuário ao passo que falta.

## 4. Fluxos

### Vendedor
1. Informa CPF e telefone (`PUT /me/identity`) — uma vez.
2. Cria o anúncio (`POST .../events/{id}/listings`, multipart): tipo de ingresso, `qty`, `unitPriceCents` (≤ valor de face), `codes` (um código por ingresso) e a prova (JPG/PNG/WebP/PDF até 8 MB). Status: **`pending_review`**.
3. O admin aprova (**`live`**) ou rejeita (**`rejected`** com `reviewReason`). Se rejeitado: `POST .../listings/{id}/resubmit` (até **3 envios** no total).
4. Quando alguém compra e paga, o pedido vira **`awaiting_transfer`**. O vendedor transfere o ingresso **pela ticketeira**, para o e-mail/conta do comprador, e toca em **"Já transferi"** (`POST .../orders/{id}/transferred`).
5. O valor é liberado quando o comprador confirma (ou em 48h sem resposta). Na tela do pedido o vendedor vê `sellerNetCents` (o que recebe) e `feeCents`.

### Comprador
1. Escolhe o show no hub → o anúncio → a quantidade → **Reservar** (`POST .../listings/{id}/orders` com `Idempotency-Key`). Mostrar contagem regressiva até `reservedUntil` (15 min).
2. **Pagar**: hoje o pagamento é **simulado** — `POST .../orders/{id}/pay` (aparece só se `canPay` e `payment.provider == "fake"`). Com o gateway real, `payment` trará os dados da cobrança (Pix etc.) e o `status` mudará sozinho depois do pagamento (polling).
3. Depois de pagar, o status é **`awaiting_transfer`**: mostrar "O vendedor tem até `transferDeadline` para transferir".
4. Quando o vendedor marca **`transferred`**, o comprador confere na ticketeira e **confirma** (`POST .../confirm`) ou **abre disputa** (`POST .../dispute`) até `confirmDeadline`.
5. Em **`completed`**, oferecer **avaliar** o vendedor (`POST .../review`, nota 1–5, uma vez).

## 5. Estados e textos sugeridos

**Anúncio (`status`)**

| status | Texto | Observação |
|---|---|---|
| `pending_review` | Em análise | aguardando o admin |
| `live` | No ar | só aparece no hub se `qtyAvailable > 0`; `qtyAvailable == 0` = "Esgotado" |
| `rejected` | Rejeitado | mostrar `reviewReason`; botão reenviar se `canResubmit` |
| `cancelled` | Cancelado | |
| `closed` | Encerrado | o show começou |

**Pedido (`status`)**

| status | Texto (comprador) | Texto (vendedor) |
|---|---|---|
| `reserved` | Reservado — pague em MM:SS | Reservado por um comprador |
| `awaiting_transfer` | Pago — aguardando o vendedor transferir | Transfira o ingresso até `transferDeadline` |
| `transferred` | Confirme o recebimento até `confirmDeadline` | Aguardando o comprador confirmar |
| `completed` | Concluído | Concluído — valor liberado |
| `disputed` | Em disputa — o admin vai decidir | Em disputa — responda ao comprador |
| `refunded` | Reembolsado | Reembolsado ao comprador |
| `expired` | Reserva expirada | — |
| `cancelled` | Cancelado | — |

`closeReason` explica o fim: `reservation_expired`, `buyer_cancelled`, `buyer_confirmed`, `auto_release` ("liberado automaticamente após 48h"), `seller_no_transfer` ("o vendedor não transferiu no prazo — reembolso automático"), `dispute_refund`, `dispute_release`, `admin_refund`, `late_payment`.

## 6. Endpoints do fã

Todos com prefixo `/artists/{slug}/resale` (exceto `/me/identity`). Resumo dos corpos; os modelos completos estão em `/docs` (Swagger) da API.

### Identidade (global)
- `GET /me/identity` → `{ hasCpf, hasPhone, cpfMasked: "***.***.***-25", phoneMasked: "(**) *****-1234", level: "none|declared|verified" }` — **CPF e telefone nunca voltam completos**.
- `PUT /me/identity` `{ cpf, phone }` → igual ao GET. Erros: `INVALID_CPF`, `INVALID_PHONE`, `CPF_IN_USE` (409), `CPF_LOCKED` (409: o CPF não troca depois de informado; o telefone pode).
- `POST /me/identity/verify/email/start|confirm` → `501` (MFA por e-mail ainda não existe; é o ponto de extensão).

### Hub e anúncios
- `GET /me/eligibility` → `{ canBuy, canSell, missing[] }`
- `GET /events` → `[{ id, date, city, venue, time, listingsCount, fromPriceCents }]` (só shows com a revenda liberada).
- `GET /events/{eventId}` → `{ event, ticketTypes: [{ id, label, description, faceCents, listingsCount }] }`. `faceCents` é o **teto**: use no formulário de venda. Se a revenda estiver fechada → `409 RESALE_CLOSED` com o motivo em `detail`.
- `GET /events/{eventId}/listings?ticketId=&sort=price|recent&page=1` → `{ items: [ListingOut], page, hasMore }` (20 por página).
- `GET /listings/{id}` → `ListingOut`.
- `POST /events/{eventId}/listings` — **multipart/form-data**: `ticketId`, `qty` (1–10), `unitPriceCents`, `codes` (**repetir o campo**, um por ingresso, igual a `qty`), `proof` (arquivo). → `201 MyListingOut`.
- `GET /me/listings` → `[MyListingOut]`
- `POST /listings/{id}/cancel` → `MyListingOut` (só sem pedidos em andamento: `HAS_ACTIVE_ORDERS`).
- `POST /listings/{id}/resubmit` — multipart: `codes` (repetir o campo, um por ingresso), `proof`.

`ListingOut`:
```json
{
  "id": "…", "eventId": "…", "ticketId": "…", "ticketLabel": "Pista",
  "faceCents": 20000, "qtyTotal": 3, "qtyAvailable": 2, "unitPriceCents": 18000,
  "createdAt": "26/10/2026",
  "seller": { /* SellerOut — ver abaixo */ }
}
```

### Vendedor — **cartão de confiança** (mostre tudo isso ao comprador)
`GET /sellers/{userId}` e o campo `seller` dos anúncios:
```json
{
  "userId": "…", "handle": "@maria", "displayName": "Maria S.", "avatar": "/uploads/…",
  "memberSince": "03/02/2026", "completedSales": 12,
  "avgRating": 4.8, "ratingCount": 9,
  "clubs": [ { "name": "Fã clube oficial", "slug": "oficial", "position": "member|helper|owner" } ],
  "isMember": true,
  "identityLevel": "declared", "identityVerified": false
}
```
Sugestão de UI: selo "Identidade informada" quando `identityLevel == "declared"` e "Identidade verificada" quando `identityVerified`; selo de membro; "12 vendas concluídas · ★ 4,8 (9)"; "No app desde 03/02/2026"; fã clube(s) com a posição (dono/ajudante/membro). Nunca há CPF, telefone ou e-mail nessas respostas.
- `GET /sellers/{userId}/reviews?page=` → `[{ id, rating, comment, createdAt, buyerName }]`

### Pedidos
- `POST /listings/{id}/orders` `{ qty, transferTo }` + header `Idempotency-Key` → `201 OrderOut`. `transferTo` é o e-mail da conta do comprador na ticketeira (para onde o vendedor transfere); vazio = o e-mail do cadastro. Erro `TRANSFER_TO_INVALID` (400). Erros: `QTY_UNAVAILABLE` (409, alguém levou antes), `OWN_LISTING`, `ALREADY_RESERVED`, `TOO_MANY_RESERVATIONS` (429, máx. 3 reservas em aberto), `RESALE_CLOSED`, `LISTING_NOT_LIVE`, `NOT_ELIGIBLE`, `PRICE_ABOVE_FACE`.
- `GET /me/orders?role=buyer|seller|all` → `[OrderOut]`
- `GET /orders/{id}` → `OrderOut`
- `POST /orders/{id}/pay` — pagamento simulado (só `canPay`).
- `POST /orders/{id}/cancel` — comprador, só `reserved`.
- `POST /orders/{id}/transferred` — vendedor.
- `POST /orders/{id}/confirm` — comprador.
- `POST /orders/{id}/dispute` `{ reasonCode: "not_received|invalid_ticket|wrong_type|other", description }` — comprador.
- `POST /orders/{id}/dispute/reply` `{ text }` — vendedor → `DisputeOut`.
- `POST /orders/{id}/review` `{ rating: 1..5, comment }` — comprador, só `completed`, uma vez.

`OrderOut` (campos principais):
```json
{
  "id": "…", "status": "awaiting_transfer", "role": "buyer",
  "eventId": "…", "eventCity": "Campinas", "eventDate": "2031-09-12", "eventVenue": "Arena",
  "ticketLabel": "Pista", "qty": 2, "unitPriceCents": 18000,
  "grossCents": 36000, "feeCents": 5400, "sellerNetCents": 30600,
  "reservedUntil": "…", "paidAt": "…", "transferDeadline": "…", "transferredAt": null,
  "confirmDeadline": null, "closedAt": null, "closeReason": "",
  "counterparty": { /* SellerOut — só para o comprador */ },
  "buyerHandle": null, "buyerName": null,        // só para o vendedor: handle e nome abreviado
  "dispute": null, "reviewed": false,
  "canPay": false, "canCancel": false, "canMarkTransferred": false, "canConfirm": false,
  "canDispute": false, "canReplyDispute": false, "canReview": false,
  "payment": { "provider": "fake" }
}
```
- O **comprador** paga `grossCents`. O **vendedor** recebe `sellerNetCents` (= bruto − `feeCents`). Mostre cada um o que lhe cabe.
- O vendedor **não** vê dados pessoais do comprador, só `buyerHandle`/`buyerName` e, **depois do pagamento**, `transferTo` (a conta da ticketeira que o próprio comprador informou para receber o ingresso). O comprador vê o seu `transferTo` sempre.
- Do outro lado, **depois do pagamento** o comprador recebe `sellerPhone` (só dígitos, com DDD, sem o +55) para falar com o vendedor no WhatsApp (`https://wa.me/55{sellerPhone}`). Antes de pagar, para o vendedor, para o admin e depois de reembolso ou cancelamento vem `null`.
- `createdAt` é quando a reserva foi feita (primeira etapa da linha do tempo).

## 7. Endpoints do admin do ambiente

Prefixo `/artists/{slug}/resale/admin` (só admin do ambiente; senão `403`).

| Endpoint | Para quê |
|---|---|
| `GET/PUT /settings` `{ feeBps }` | taxa em basis points (`100` = 1%, máx. `3000`); vale só para pedidos novos |
| `GET /events` | shows futuros com `ticketingSoldOut`, `resaleOpen`, `isOpen`, `timeReadable`, contagem de anúncios |
| `PUT /events/{id}` `{ ticketingSoldOut, resaleOpen }` | **as duas chaves do show**. Para abrir: marcar "esgotou" antes, show futuro e horário legível (ex.: `22h`) — erros `NOT_SOLD_OUT`, `TIME_UNREADABLE`, `EVENT_PAST` |
| `GET /listings?status=pending_review` | fila de provas |
| `GET /listings/{id}` | detalhe: **códigos dos ingressos decifrados**, perfil do vendedor, `verifierStatus`, histórico |
| `GET /listings/{id}/proof` | baixa a prova (arquivo privado; abrir em nova aba/baixar) |
| `POST /listings/{id}/approve` | coloca no ar |
| `POST /listings/{id}/reject` `{ reason }` | rejeita (motivo obrigatório) |
| `GET /orders?status=` | todos os pedidos |
| `GET /ledger?orderId=` | livro-razão (somente leitura) |
| `POST /orders/{id}/refund` | reembolsa pedido pago e não transferido |
| `GET /disputes?status=open` | fila de disputas (mais antigas primeiro), já com o pedido |
| `POST /disputes/{id}/decide` `{ decision: "refund"|"release", note }` | decide. `CONFLICT_OF_INTEREST` se o admin é parte do pedido |
| `POST /reviews/{id}/hide` | oculta avaliação abusiva |

Dica: ao decidir uma disputa, mostre os dois lados lado a lado (`description` do comprador, `sellerReply`), os códigos e a prova do anúncio.

## 8. Códigos de erro (`code`)

| code | HTTP | Quando |
|---|---|---|
| `RESALE_CLOSED` | 409 | revenda não liberada, show a menos de 4h ou já passou |
| `NOT_ELIGIBLE` | 403 | cadastro incompleto (ver `GET /me/eligibility`) |
| `PRICE_ABOVE_FACE` | 400/409 | preço acima do valor de face |
| `QTY_UNAVAILABLE` | 409 | o saldo acabou antes da sua reserva |
| `QTY_INVALID` / `CODES_COUNT` / `CODE_INVALID` / `CODES_REPEATED` | 400 | formulário de venda |
| `PROOF_REQUIRED` / `PROOF_TYPE` / `PROOF_TOO_BIG` | 400 | prova ausente, tipo inválido (valida o conteúdo) ou > 8 MB |
| `CODE_DUPLICATE` / `PROOF_DUPLICATE` | 409 | ingresso ou arquivo já anunciado |
| `RATE_LIMIT` / `TOO_MANY_RESERVATIONS` | 429 | muitos anúncios na hora / 3 reservas em aberto |
| `OWN_LISTING` | 403 | tentando comprar o próprio anúncio |
| `ALREADY_RESERVED` | 409 | reserva em aberto no mesmo anúncio |
| `LISTING_NOT_LIVE` | 409 | anúncio cancelado/encerrado/em análise |
| `RESERVATION_EXPIRED` | 409 | pagou depois dos 15 min |
| `INVALID_STATE` | 409 | ação não vale mais para o estado atual — **recarregue o pedido** |
| `DISPUTED` | 409 | pedido em disputa |
| `HAS_ACTIVE_ORDERS` | 409 | anúncio com compras em andamento |
| `ATTEMPTS_EXHAUSTED` | 409 | 3 envios de prova usados |
| `ALREADY_REVIEWED` / `RATING_INVALID` | 409/400 | avaliação |
| `IDEMPOTENCY_CONFLICT` / `IDEMPOTENCY_KEY` | 409/400 | chave reutilizada com outro pedido / tamanho inválido |
| `CPF_IN_USE` / `CPF_LOCKED` / `INVALID_CPF` / `INVALID_PHONE` | 409/400 | identidade |
| `NOT_PARTY` / `NOT_OWNER` / `CONFLICT_OF_INTEREST` | 403 | permissão |
| `PAYMENT_NOT_CONFIGURED` / `KEYS_MISSING` | 503 | pagamento ou chaves da revenda não configurados no servidor (mostrar "indisponível no momento") |
| `AMOUNT_MISMATCH` | 400 | webhook do gateway com valor diferente do pedido (não é para o usuário final) |
| `CHANGE_BLOCKED` / `HAS_RESALE` | 409 | admin tentando mudar data/horário de um show com compra em andamento, ou apagar show/ambiente com revenda |

## 9. Pontos de atenção (comportamento da API que o front deve respeitar)

- **Não calcule preço nem prazo no front.** Use `grossCents`, `feeCents`, `sellerNetCents` e os `*Deadline` que vêm prontos; formate em horário de Brasília.
- Depois de **qualquer ação**, use o `OrderOut` devolvido para atualizar a tela (já vem com as flags novas). Em `409 INVALID_STATE`, recarregue.
- O hub só lista shows liberados; se um show fechar com o usuário na tela, a API responde `RESALE_CLOSED` — mostre o `detail`.
- Reserva expirada devolve o saldo ao anúncio automaticamente; a lista pode mostrar menos/mais saldo entre uma leitura e outra.
- Sempre que mostrar um vendedor, mostre o **cartão de confiança** completo (é o ponto da funcionalidade).
- A prova e os códigos dos ingressos **só o admin vê**. O vendedor não consegue baixar a própria prova depois de enviar.
- Upload da prova: envie o `File` do navegador em `FormData` (não JSON). Para `codes`, faça `form.append("codes", código)` uma vez por ingresso.
- `canPay` só vem `true` quando o pagamento simulado está ligado (sempre no dev; no servidor só com `RESALE_ALLOW_FAKE_PAYMENT=true`). Se vier `false` numa reserva ativa, mostre "pagamento indisponível no momento".
- Ambiente de desenvolvimento: o pagamento é simulado e sempre dá certo. O provedor real entra depois sem mudar as telas (o campo `payment` do pedido passa a trazer os dados da cobrança).

## 10. Estilo

Seguir o app: fundo escuro `#120907`, destaque âmbar `#FE9900`, fontes **Playfair Display** (títulos), **Archivo** (texto) e **DM Mono** (rótulos). Reaproveitar `Sheet`, `btn`, `tag`, `mono` e os componentes de `src/components/fan`. Tudo responsivo em 430 px (celular primeiro). Estilização refinada fica para depois; priorize páginas simples e claras.
