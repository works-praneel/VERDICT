#!/usr/bin/env bash
set -e

echo "==> Installing Python dependencies"
pip install -r requirements.txt --break-system-packages

echo "==> Checking for Ollama"
if ! command -v ollama &> /dev/null; then
    echo "Ollama is not installed. Install it from https://ollama.com/download"
    echo "Then run: ollama pull qwen2.5-coder"
    exit 1
fi

echo "==> Pulling local model (qwen3:8b — override with VERDICT_MODEL if you use a different tag)"
ollama pull qwen3:8b

echo "==> Setup complete. Try:"
echo "    python -m verdict.cli review feature/hardcoded-secret"
