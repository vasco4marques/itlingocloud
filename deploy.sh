#!/usr/bin/env bash
# Build, push and deploy the ITLingoCloud Odoo image to the droplet.
#
# Usage:
#   ./deploy.sh               build + push + deploy
#   ./deploy.sh --skip-build  deploy the image for the current git sha (already pushed)
#
# Only valid after the Docker cutover — aborts if the
# old systemd odoo service is still active. Sudo password will be prompted once
# on the server to install the deployment files and update ODOO_TAG in /opt/odoo/.env.
set -euo pipefail

IMAGE=vasco4marques/itlingo-odoo
SERVER=itlingo-admin@46.101.130.155
SSH_KEY=~/.ssh/digital_ocean

cd "$(dirname "$0")"

if [[ -n "$(git status --porcelain custom-addons)" ]]; then
    echo "WARNING: uncommitted changes in custom-addons/ — the image tag won't match the code it contains." >&2
    read -rp "Continue anyway? [y/N] " reply
    [[ $reply == [yY] ]] || exit 1
fi
SHA=$(git rev-parse --short HEAD)

if [[ ${1:-} != --skip-build ]]; then
    docker build -t "$IMAGE:$SHA" -t "$IMAGE:latest" .
    docker push "$IMAGE:$SHA"
    docker push "$IMAGE:latest"
fi

echo ">>> Deploying $IMAGE:$SHA to $SERVER"
scp -i "$SSH_KEY" docker-compose.yml "$SERVER:/tmp/docker-compose.deploy.yml"
scp -i "$SSH_KEY" Makefile.droplet "$SERVER:/tmp/Makefile.odoo.deploy"
ssh -i "$SSH_KEY" -t "$SERVER" "
    set -euo pipefail
    if systemctl is-active --quiet odoo; then
        echo 'odoo.service is still active — this script only applies after the Docker cutover.' >&2
        exit 1
    fi
    cd /opt/odoo
    # /opt/odoo is odoo:odoo 755 and docker-compose.yml is root-owned, so the
    # upload lands in /tmp and is installed from here under the same sudo.
    sudo install -m 644 -o root -g root /tmp/docker-compose.deploy.yml docker-compose.yml
    sudo install -m 644 -o root -g root /tmp/Makefile.odoo.deploy Makefile
    rm -f /tmp/docker-compose.deploy.yml /tmp/Makefile.odoo.deploy
    sudo sed -i 's/^ODOO_TAG=.*/ODOO_TAG=$SHA/' .env
    make pull
    make upgrade
"
echo ">>> Deployed $IMAGE:$SHA"
