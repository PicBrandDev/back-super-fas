# Chat privado entre fãs — contrato da API

Conversa 1:1 entre dois fãs **do mesmo ambiente** (cantor). Só texto: não há envio de foto, vídeo nem arquivo.
O front atualiza por polling (`after_id`), não há websocket.

Todas as rotas exigem login (`Authorization: Bearer <token>`) e um ambiente visível para quem chama
(mesma regra das outras rotas do fã: ambiente em configuração só aparece para quem administra).
Sem login: `401`. Ambiente inexistente: `404`.

Como no resto da API, o JSON de resposta vem em **camelCase** (`lastMessageAt`, `conversationId`, `senderId`,
`readAt`, `isMe`). No corpo das requisições os nomes em camelCase e em snake_case são aceitos (`userId` ou `user_id`).

> **Atenção aos tipos dos ids.** O id de **usuário** é texto no banco (ex.: `"a1b2c3d4e5"`), então
> `ChatUserOut.id`, `MessageOut.senderId`, o `userId` do corpo, o `{user_id}` de `/fans/{user_id}`,
> `PublicProfileOut.id` e `AuthorOut.id` são **string**. Os ids de **conversa** e de **mensagem** são
> **número inteiro** (é o que permite o `after_id`). Para saber se a mensagem é sua, use `mine`, não compare ids.

## Tipos

```ts
type ChatUserOut = { id: string; name: string; handle: string | null; avatar: string | null }  // avatar: "/uploads/x.jpg"

type MessageOut = {
  id: number
  conversationId: number
  senderId: string
  body: string
  createdAt: string        // ISO 8601 com fuso (UTC)
  readAt: string | null    // quando o outro leu
  mine: boolean            // true = enviada por quem chamou
}

type ConversationOut = {
  id: number
  other: ChatUserOut       // a outra pessoa da conversa
  lastMessage: MessageOut | null
  lastMessageAt: string | null
  unread: number           // mensagens do outro ainda não lidas por quem chamou
}

type PublicProfileOut = {
  id: string
  name: string
  handle: string | null
  avatar: string | null
  club: { slug: string; name: string; avatar: string | null } | null  // fã clube dele neste ambiente
  points: number | null    // pontos de sorte neste ambiente (null se não participa)
  rank: number | null      // posição no ranking Fã Super (null se ainda não pontuou)
  isMe: boolean
  posts: PostOut[]         // até 10 posts mais recentes dele neste ambiente (mesmo formato do mural)
}
```

## Rotas

### `GET /artists/{slug}/chat/conversations`

Minhas conversas neste ambiente, da mais recente para a mais antiga (`lastMessageAt` desc; conversa sem
mensagem fica no fim).

```json
[
  {
    "id": 12,
    "other": { "id": "a1b2c3d4e5", "name": "Marina Esteves", "handle": "@marina.esteves", "avatar": "/uploads/real-user-a1b2c3d4e5.jpg" },
    "lastMessage": {
      "id": 340, "conversationId": 12, "senderId": "a1b2c3d4e5", "body": "Bora no show de BH?",
      "createdAt": "2026-10-26T21:14:03.120000Z", "readAt": null, "mine": false
    },
    "lastMessageAt": "2026-10-26T21:14:03.120000Z",
    "unread": 2
  }
]
```

### `POST /artists/{slug}/chat/conversations`

Abre (ou devolve, se já existir) a conversa com outro fã. Há uma só conversa por par de pessoas em cada ambiente.

```json
{ "userId": "a1b2c3d4e5" }
```

Resposta `200`: `ConversationOut` (mesmo formato do item da lista; `lastMessage` é `null` numa conversa nova).

Erros: `422` se `userId` é o próprio usuário; `404` se o usuário não existe ou não é fã deste ambiente.

### `GET /artists/{slug}/chat/conversations/{id}`

Resposta `200`: `ConversationOut`. `404` se a conversa não existe neste ambiente; `403` se quem chama não está nela.

### `GET /artists/{slug}/chat/conversations/{id}/messages?after_id=<int>&limit=50`

Mensagens em ordem crescente de `id`.

- Sem `after_id`: as últimas `limit` mensagens (para abrir a conversa).
- Com `after_id`: só as que chegaram depois dela (polling). Lista vazia = nada novo.
- Com `before_id`: as `limit` anteriores a ela (carregar o histórico ao rolar para cima). Lista vazia = chegou ao começo.
- `limit`: 1 a 200 (padrão 50).

```json
[
  { "id": 339, "conversationId": 12, "senderId": "f0e1d2c3b4", "body": "Vou sim!", "createdAt": "2026-10-26T21:13:40Z", "readAt": "2026-10-26T21:13:52Z", "mine": true },
  { "id": 340, "conversationId": 12, "senderId": "a1b2c3d4e5", "body": "Bora no show de BH?", "createdAt": "2026-10-26T21:14:03Z", "readAt": null, "mine": false }
]
```

Erros: `403`/`404` como acima.

### `POST /artists/{slug}/chat/conversations/{id}/messages`

```json
{ "body": "Chego às 22h na porta 3" }
```

Resposta `201`: `MessageOut` (com `mine: true`). Atualiza o `lastMessageAt` da conversa.

Regras do texto (depois de tirar os espaços das pontas): de 1 a 1000 caracteres, e **só texto**. Responde `422`
com `detail` em português quando a mensagem:

- está vazia ou passa de 1000 caracteres;
- tem `data:` (imagem embutida);
- tem link para imagem ou vídeo (`.jpg`, `.jpeg`, `.png`, `.gif`, `.webp`, `.heic`, `.heif`, `.bmp`, `.svg`,
  `.avif`, `.tif(f)`, `.mp4`, `.mov`, `.webm`, `.m4v`, `.avi`, `.mkv`, `.3gp`);
- tem link para `/uploads/`.

```json
{ "detail": "O chat é só de texto: não dá para enviar fotos, vídeos ou links de mídia." }
```

### `POST /artists/{slug}/chat/conversations/{id}/read`

Marca como lidas as mensagens do outro nesta conversa. Resposta `200`:

```json
{ "unread": 0 }
```

### `GET /artists/{slug}/chat/unread`

Total de mensagens não lidas em todas as minhas conversas deste ambiente (badge da navegação).

```json
{ "count": 3 }
```

### `GET /artists/{slug}/fans/{user_id}`

Perfil público de um fã neste ambiente (tela aberta ao tocar no autor de um post). `404` se o usuário não existe.

```json
{
  "id": "a1b2c3d4e5",
  "name": "Marina Esteves",
  "handle": "@marina.esteves",
  "avatar": "/uploads/real-user-a1b2c3d4e5.jpg",
  "club": { "slug": "vintage-bh", "name": "Vintage BH", "avatar": "/uploads/real-clube-vintage-bh.jpg" },
  "points": 120,
  "rank": 7,
  "isMe": false,
  "posts": [ { "id": "9f8e7d6c5b", "kind": "galera", "author": { "...": "..." }, "text": "...", "...": "..." } ]
}
```

## Autor dos posts (`AuthorOut`)

O autor de cada post do mural (`GET /artists/{slug}/posts` e afins) ganhou dois campos, para o front abrir o
perfil e mostrar a foto:

```json
{ "name": "Marina Esteves", "handle": "@marina.esteves", "initial": "M", "id": "a1b2c3d4e5", "avatar": "/uploads/real-user-a1b2c3d4e5.jpg" }
```

Em post oficial (autor = o cantor), `id` e `avatar` vêm `null`.
