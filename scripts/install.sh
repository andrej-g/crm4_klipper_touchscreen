#!/usr/bin/env bash
# Install from this clone as the login user. Never run the whole script with sudo.
set -Eeuo pipefail
REPO=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
DEPS=0; SERVICE=1; ENABLE=0; START=0; LINGER=0
usage() {
    cat <<'EOF'
Usage: bash scripts/install.sh [--install-deps] [--no-service] [--enable] [--start] [--linger]
Installs .venv and a user service; preserves existing config. Defaults to dry-run,
with service neither enabled nor started. --install-deps uses sudo apt and adds
the login user to dialout. --linger uses sudo loginctl for boot without login.
EOF
}
while (($#)); do
    case "$1" in
        --install-deps) DEPS=1 ;;
        --no-service) SERVICE=0 ;;
        --enable) ENABLE=1 ;;
        --start) START=1 ;;
        --linger) LINGER=1 ;;
        -h|--help) usage; exit 0 ;;
        *) usage >&2; exit 2 ;;
    esac
    shift
done
[[ $EUID != 0 ]] || { echo 'Run as your login user, not sudo bash install.sh.' >&2; exit 2; }
[[ $(uname -s) == Linux ]] || { echo 'This installer requires Linux.' >&2; exit 2; }
if ((!SERVICE && (ENABLE || START || LINGER))); then
    echo '--no-service cannot be combined with --enable, --start or --linger.' >&2; exit 2
fi
if command -v systemctl >/dev/null && systemctl --user is-active --quiet crm4bridge.service; then
    echo 'Stop the existing bridge first: systemctl --user stop crm4bridge' >&2; exit 1
fi
if ((DEPS)); then
    command -v apt-get >/dev/null || { echo '--install-deps requires apt-get.' >&2; exit 1; }
    sudo apt-get update
    sudo apt-get install -y python3 python3-venv python3-pip python3-dev build-essential \
        libjpeg-dev zlib1g-dev libfreetype6-dev fonts-dejavu-core
    if getent group dialout >/dev/null; then
        sudo usermod -aG dialout "$(id -un)"
        echo 'Reboot before starting the service if dialout membership was newly added.'
    fi
fi
command -v python3 >/dev/null || { echo 'Install Python 3.9+ and python3-venv first.' >&2; exit 1; }
python3 -c 'import sys; assert sys.version_info >= (3, 9), "Python 3.9+ required"'
python3 -m venv "$REPO/.venv"
"$REPO/.venv/bin/python" -m pip install -e "$REPO[serial]"
"$REPO/.venv/bin/python" -m pip check
if ((SERVICE)); then
    "$REPO/.venv/bin/python" "$REPO/scripts/install_service.py" --repo "$REPO"
    systemctl --user daemon-reload
    if ((LINGER)); then sudo loginctl enable-linger "$(id -un)"; fi
    if ((ENABLE)); then systemctl --user enable crm4bridge.service; fi
    if ((START)); then systemctl --user start crm4bridge.service; fi
fi
echo "Installed. Config: ${XDG_CONFIG_HOME:-$HOME/.config}/crm4bridge/crm4bridge.cfg"
echo 'Edit moonraker/screen, test dry-run, then set dry_run = false when ready.'
