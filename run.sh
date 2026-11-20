#!/usr/bin/env bash
# ==============================================================================
# Site Downloader & React Converter - Unix Launcher
# ==============================================================================

set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"

# 1. Check for Python 3
if ! command -v python3 &> /dev/null; then
    echo "⚡ Python 3 is not installed on this system."
    echo "Attempting automated installation..."
    if command -v brew &> /dev/null; then
        brew install python3
    elif command -v apt-get &> /dev/null; then
        sudo apt-get update && sudo apt-get install -y python3 python3-pip
    elif command -v dnf &> /dev/null; then
        sudo dnf install -y python3 python3-pip
    elif command -v pacman &> /dev/null; then
        sudo pacman -Sy --noconfirm python python-pip
    else
        echo "❌ Please install Python 3 manually from https://www.python.org/downloads/"
        exit 1
    fi
fi

# 2. Run Site Downloader
exec python3 "$DIR/site_downloader.py" "$@"
