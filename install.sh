#!/usr/bin/env bash
# Install kernel-build-mcp on a remote Linux machine.
# Usage: scp -r kernel-build-mcp/ user@host:~/  && ssh user@host "~/kernel-build-mcp/install.sh"

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== kernel-build-mcp installer ==="

# Check Python 3.10+
if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 not found. Install Python 3.10+."
    exit 1
fi

PYVER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "Python version: $PYVER"

# Install with pip
echo "Installing kernel-build-mcp..."
pip3 install --user -e "$SCRIPT_DIR"

# Verify
echo "Verifying installation..."
python3 -c "from kernel_build_mcp import server; print('OK: server module loads')"

echo ""
echo "=== Installation complete ==="
echo ""
echo "Next steps:"
echo "  1. Configure: python3 -m kernel_build_mcp.server"
echo "     (first run creates ~/.config/kernel-build-mcp/config.json)"
echo "  2. Edit config: vi ~/.config/kernel-build-mcp/config.json"
echo "  3. Set kernel_dir and cross_compile paths"
echo ""
echo "Or configure remotely via Claude Code set_config tool."
