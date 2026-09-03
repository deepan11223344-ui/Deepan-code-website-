#!/usr/bin/env bash
# DeepanCode Linux & macOS Terminal One-Click Installer

set -e

echo -e "\033[1;36m=============================================\033[0m"
echo -e "\033[1;36m Installing DeepanCode AI Agent (POSIX)   \033[0m"
echo -e "\033[1;36m=============================================\033[0m"

if ! command -v python3 &> /dev/null; then
    echo -e "\033[1;31mError: python3 is required but not installed.\033[0m"
    exit 1
fi

echo -e "\033[1;33m[1/3] Upgrading pip and installing required dependencies...\033[0m"
python3 -m pip install --upgrade pip --break-system-packages 2>/dev/null || python3 -m pip install --upgrade pip
python3 -m pip install -e . --break-system-packages 2>/dev/null || python3 -m pip install -e .

echo -e "\033[1;33m[2/3] Verifying installation...\033[0m"
python3 -c "import deepans_code; print('Deepans-code module successfully imported!')"

echo -e "\033[1;32m[3/3] Setup complete!\033[0m"
echo ""
echo -e "\033[1;36mTo start DeepanCode, run:\033[0m"
echo "    deepans-code"
echo -e "\033[1;36mOr:\033[0m"
echo "    python3 -m deepans_code"
echo ""
echo -e "\033[1;33mTo configure one-time API keys:\033[0m"
echo "    deepans-code"
echo "    /connect openrouter <YOUR_API_KEY>"
chmod +x install.sh
