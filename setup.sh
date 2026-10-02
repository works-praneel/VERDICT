#!/usr/bin/env bash
set -e

echo "==> Installing Python dependencies"
pip install -r requirements.txt --break-system-packages

echo "==> Checking for Ollama"
if ! command -v ollama &> /dev/null; then
    echo "Ollama is not installed. Install it from https://ollama.com/download"
    echo "Then install the model configured through VERDICT_MODEL."
    exit 1
fi

MODEL="${VERDICT_MODEL:-qwen2.5-coder:14b}"

echo "==> Pulling local model ($MODEL)"
ollama pull "$MODEL"

echo "==> Setup complete. Try:"
echo "    python -m verdict.cli review feature/hardcoded-secret"