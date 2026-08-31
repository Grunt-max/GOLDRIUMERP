#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR=/srv/goldrium/app
VENV_DIR=/srv/goldrium/venv
BACKUP_DIR=/srv/goldrium/backups
ENV_FILE=/etc/goldrium-erp.env
SERVICE=goldrium-erp.service
BRANCH=main
LOCK_FILE=/run/lock/goldrium-deploy.lock

if [[ ${EUID} -ne 0 ]]; then
    echo "Run this deployment as root." >&2
    exit 1
fi

exec 9>"${LOCK_FILE}"
if ! flock -n 9; then
    echo "Another Goldrium deployment is already running." >&2
    exit 1
fi

if [[ ! -f ${ENV_FILE} ]]; then
    echo "Missing environment file: ${ENV_FILE}" >&2
    exit 1
fi

cd "${APP_DIR}"
runuser -u goldrium -- git fetch --prune origin "${BRANCH}"

previous_commit=$(runuser -u goldrium -- git rev-parse HEAD)
target_commit=$(runuser -u goldrium -- git rev-parse "origin/${BRANCH}")

if [[ ${previous_commit} == "${target_commit}" ]]; then
    echo "Already deployed: ${target_commit}"
    exit 0
fi

timestamp=$(date +%Y%m%d-%H%M%S)
db_backup="${BACKUP_DIR}/predeploy-${timestamp}-db.sqlite3"
media_backup="${BACKUP_DIR}/predeploy-${timestamp}-media.tar.gz"

mkdir -p "${BACKUP_DIR}"
sqlite3 "${APP_DIR}/db.sqlite3" ".backup '${db_backup}'"
tar -czf "${media_backup}" -C "${APP_DIR}" media

service_stopped=0
rollback() {
    exit_code=$?
    if (( service_stopped )); then
        systemctl stop "${SERVICE}" || true
        runuser -u goldrium -- git reset --hard "${previous_commit}" || true
        cp -f "${db_backup}" "${APP_DIR}/db.sqlite3" || true
        chown goldrium:goldrium "${APP_DIR}/db.sqlite3" || true
        systemctl start "${SERVICE}" || true
    fi
    echo "Deployment failed; previous code and database were restored." >&2
    exit "${exit_code}"
}
trap rollback ERR

systemctl stop "${SERVICE}"
service_stopped=1

runuser -u goldrium -- git reset --hard "origin/${BRANCH}"
runuser -u goldrium -- "${VENV_DIR}/bin/python" -m pip install -r requirements.txt

set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

runuser -u goldrium --preserve-environment -- "${VENV_DIR}/bin/python" manage.py check --deploy
runuser -u goldrium --preserve-environment -- "${VENV_DIR}/bin/python" manage.py migrate --noinput
runuser -u goldrium --preserve-environment -- "${VENV_DIR}/bin/python" manage.py collectstatic --noinput

systemctl start "${SERVICE}"

for _ in {1..20}; do
    if curl --fail --silent --output /dev/null http://127.0.0.1:8000/login/; then
        service_stopped=0
        trap - ERR
        echo "Deployed ${target_commit} successfully."
        exit 0
    fi
    sleep 1
done

echo "Service did not pass the local health check." >&2
false
