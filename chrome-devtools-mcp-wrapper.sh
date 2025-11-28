#!/usr/bin/env nix-shell
# Pinned nixpkgs: nixos-25.05 (sha256: 1915r28xc4znrh2vf4rrjnxldw2imysz819gzhk9qlrkqanmfsxd)
#! nix-shell -E "let pkgs = import (builtins.fetchTarball { url = \"https://github.com/nixos/nixpkgs/tarball/25.05\"; sha256 = \"1915r28xc4znrh2vf4rrjnxldw2imysz819gzhk9qlrkqanmfsxd\"; }) {}; in pkgs.mkShell { buildInputs = with pkgs; [ nodejs_22 chromium ]; }"
#! nix-shell -i bash
# shellcheck shell=bash
# Wrapper script to run chrome-devtools-mcp with correct Node.js and Chromium from nix-shell
# Uses project-local Chrome profile to avoid tainting global settings

set -euo pipefail
cd "$(dirname "$0")"

# Set up Chrome paths
export CHROMIUM_PATH="$(command -v chromium)"
export CHROME_PROFILE_DIR="$(pwd)/.chrome-profile"

# Create project-local Chrome profile directory if it doesn't exist
mkdir -p "$CHROME_PROFILE_DIR"

# Pin to specific version for reproducibility (not @latest)
npx chrome-devtools-mcp@0.10.1 --executablePath "$CHROMIUM_PATH" --userDataDir "$CHROME_PROFILE_DIR"
