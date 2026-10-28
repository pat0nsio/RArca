#!/usr/bin/env bash
# Deja RArca funcionando desde cero: modelos, contenedores e índice. Se puede volver a correr sin romper nada.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] && set -a && . ./.env && set +a  # RARCA_HOST, para el mensaje final

GGUF=data/modelos/bge-reranker-v2-m3-Q8_0.gguf
if [ ! -f "$GGUF" ]; then  # el contenedor del reranker no arranca sin el modelo
  mkdir -p data/modelos
  curl -fL -o "$GGUF.part" https://huggingface.co/gpustack/bge-reranker-v2-m3-GGUF/resolve/main/bge-reranker-v2-m3-Q8_0.gguf
  mv "$GGUF.part" "$GGUF"
fi

podman-compose up -d --build

for m in qwen3:8b bge-m3 llama3.1:8b; do  # llama3.1 solo lo usa la evaluación (juez de exactitud)
  podman-compose exec ollama ollama pull "$m"
done

podman-compose run --rm api python -m app.ingest
echo "Listo: http://${RARCA_HOST:-127.0.0.1}:8000"
