#!/usr/bin/env bash
# rube installer — rube.works
# Installs the rube CLI to ~/.local/bin/rube (or /usr/local/bin with sudo)
# Zero Node.js. Pure Python (3.8+). No pip packages required.
set -euo pipefail

REPO="flatfinderai-cyber/rube-works"
RAW_BASE="https://raw.githubusercontent.com/${REPO}/main"
SCRIPT_URL="${RAW_BASE}/rube/rube.py"
INSTALL_DIR="${HOME}/.local/bin"
INSTALL_PATH="${INSTALL_DIR}/rube"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

info()    { echo -e "${CYAN}${BOLD}[rube]${RESET} $*"; }
success() { echo -e "${GREEN}${BOLD}[rube]${RESET} $*"; }
warn()    { echo -e "${YELLOW}${BOLD}[rube]${RESET} $*"; }
error()   { echo -e "${RED}${BOLD}[rube]${RESET} $*" >&2; exit 1; }

# ── Check Python ──────────────────────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
    error "Python 3.8+ is required. Install it from https://python.org"
fi

PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)
if (( PY_MAJOR < 3 || (PY_MAJOR == 3 && PY_MINOR < 8) )); then
    error "Python 3.8+ required (found ${PY_VER})"
fi
info "Python ${PY_VER} ✓"

# ── Check gh CLI ──────────────────────────────────────────────────────────────
if ! command -v gh &>/dev/null; then
    warn "GitHub CLI (gh) not found."
    warn "Install: https://cli.github.com  |  brew install gh  |  apt install gh"
    warn "Then run: gh auth login"
else
    info "GitHub CLI (gh) ✓"
fi

# ── Check git ─────────────────────────────────────────────────────────────────
if ! command -v git &>/dev/null; then
    error "git is required but not found."
fi
info "git ✓"

# ── Download ──────────────────────────────────────────────────────────────────
mkdir -p "$INSTALL_DIR"
info "Downloading rube to ${INSTALL_PATH} ..."

if command -v curl &>/dev/null; then
    curl -fsSL "$SCRIPT_URL" -o "$INSTALL_PATH"
elif command -v wget &>/dev/null; then
    wget -qO "$INSTALL_PATH" "$SCRIPT_URL"
else
    error "curl or wget is required to download rube"
fi

chmod +x "$INSTALL_PATH"
success "Installed rube → ${INSTALL_PATH}"

# ── PATH check ────────────────────────────────────────────────────────────────
if ! echo "$PATH" | grep -q "${INSTALL_DIR}"; then
    warn "${INSTALL_DIR} is not in your PATH."
    warn "Add one of these to your shell profile (~/.bashrc, ~/.zshrc, etc.):"
    echo ""
    echo "    export PATH=\"\$HOME/.local/bin:\$PATH\""
    echo ""
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
success "rube installed successfully!"
echo ""
echo -e "  ${BOLD}Quick start:${RESET}"
echo "    rube -p \"add unit tests\" -m 5"
echo "    rube -p \"fix linting errors\" --max-cost 5.00"
echo "    rube -p \"improve docs\" --max-duration 1h"
echo ""
echo -e "  ${BOLD}Model-agnostic:${RESET}"
echo "    rube -p \"refactor\" -m 3 --ai-cmd aider --ai-flags \"--yes\" --ai-output-format text"
echo ""
echo -e "  ${BOLD}Docs:${RESET} https://github.com/${REPO}"
echo ""
