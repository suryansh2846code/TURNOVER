#!/bin/bash
# Lodestone — one-command install for technical testers (macOS).
#   curl -LsSf https://raw.githubusercontent.com/suryansh2846code/TURNOVER/main/scripts/install.sh | bash
# or, after cloning:  bash scripts/install.sh
set -e

REPO="https://github.com/suryansh2846code/TURNOVER.git"
DIR="${LODESTONE_DIR:-$HOME/lodestone}"

echo "◆ Installing Lodestone into $DIR"

# 1. uv (fast Python package manager) — installs Python too if needed
if ! command -v uv >/dev/null 2>&1; then
  echo "→ installing uv…"
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="$HOME/.local/bin:$PATH"

# 2. clone or update
if [ -d "$DIR/.git" ]; then
  echo "→ updating existing checkout…"
  git -C "$DIR" pull --ff-only
else
  git clone --depth 1 "$REPO" "$DIR"
fi
cd "$DIR"

# 3. venv + deps (connectors + desktop; skips heavy PyTorch by default — the
#    offline 'hash' embedder is the default, works with zero downloads).
echo "→ creating venv and installing…"
uv venv
uv pip install -e ".[desktop,gmail,gdrive,notion]"

cat <<EOF

✓ Lodestone installed.

Run it as a desktop app:
    cd "$DIR" && .venv/bin/lodestone app

Or in a browser:
    cd "$DIR" && .venv/bin/lodestone serve      # → http://127.0.0.1:8787

Connectors that need NO sign-in (local-first): Local Files, Apple Mail,
Apple Calendar, iMessage  (grant Full Disk Access in System Settings).

Optional — sharper semantic recall (downloads ~a few hundred MB of PyTorch):
    uv pip install -e ".[local-embeddings]"
    echo "LODESTONE_EMBEDDING_PROVIDER=local" >> .env
EOF
