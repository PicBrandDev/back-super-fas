#!/usr/bin/env bash
# Popula o ambiente da demonstração de uma vez: contas, fã clubes, feed, ranking, anúncios, pacotes, Ingresse, chat,
# os fã clubes que o usuário da demo segue e, por último, as fotos de verdade (que substituem as de mock) e o relatório de fotos faltando.
#
# Rode na pasta do docker compose (no servidor, ~/front-super-fas):
#
#     bash ../back-super-fas/scripts/popular_demo.sh ~/fotos     # copia ~/fotos para /tmp/fotos do container antes
#     bash ../back-super-fas/scripts/popular_demo.sh             # usa o que já estiver em /tmp/fotos do container
#
# A pasta de fotos tem as subpastas rostos/, posts/ e clubes/ (veja scripts/fotos_reais.py). Os shows precisam existir
# antes (dados_exemplo.py, que usa a API). A revenda fica de fora (escondida na demo); para incluir, rode o
# mock_revenda.py à parte. Pode rodar de novo: todos os scripts da cadeia só completam o que falta ou regravam o mesmo.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FOTOS="${1:-}"

run() {
  local script="$1"
  shift
  echo
  echo "==> $script"
  sudo docker compose exec -T "$@" api python - < "$DIR/$script"
}

if [ -n "$FOTOS" ]; then
  [ -d "$FOTOS" ] || { echo "Pasta de fotos não encontrada: $FOTOS" >&2; exit 1; }
  echo "==> copiando $FOTOS para /tmp/fotos do container"
  sudo docker compose exec -T api rm -rf /tmp/fotos
  sudo docker compose cp "$FOTOS" api:/tmp/fotos
fi

# Contas e donos dos fã clubes primeiro: os mocks seguintes usam esses usuários.
run contas_vintage.py
run mock_fa_clubes.py
run mock_feed.py
run mock_ranking.py
run mock_anuncios_app.py
# Demais mocks (nenhum deles apaga foto: só completam ingressos, pacotes, prêmios, cupons, vitrines e campanhas).
run mock_agencias.py
run mock_pacotes_experiencia.py
run mock_dropnews.py
run mock_roleta.py
run mock_cupons.py
run mock_vitrines.py
run mock_campanha_cocacola.py
# O Photo Finder só abre depois do show: sem show passado o script sai com erro, e a cadeia segue sem ele.
run mock_ingressos_photo.py || echo "!! mock_ingressos_photo.py não rodou (nenhum show já aconteceu?): pulei o Photo Finder"
# Ingresse depois dos pacotes: regrava ticketeira e experiências pagas.
run mock_ingresse.py

if [ -f "$DIR/mock_chat.py" ]; then
  run mock_chat.py
else
  echo
  echo "!! scripts/mock_chat.py não existe ainda (vem com o chat privado): pulei as conversas"
fi

# Depois de todos os posts: o usuário da demo segue fã clubes até a Comunidade dele ter 16 posts ou mais (o patrocinado
# entra a cada 7, nas posições 8 e 16).
run demo_segue_clubes.py

# Fotos de verdade por último, para nenhum mock gravar foto de mentira por cima.
run fotos_reais.py -e FOTOS_DIR=/tmp/fotos
run relatorio_fotos.py

echo
echo "Pronto: ambiente da demo populado."
