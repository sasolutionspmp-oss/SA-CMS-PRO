#!/usr/bin/env bash
# Run inside the synthetic development runtime; passwords remain in environment.
set -euo pipefail
cd /home/frappe/frappe-bench
if [[ "${CIPHER_SYNTHETIC:-}" != 1 ]]; then
  echo 'This bootstrap is restricted to the synthetic development environment.' >&2
  exit 2
fi
bench set-config -g db_host db
bench set-config -gp db_port 3306
bench set-config -g redis_cache redis://redis:6379/0
bench set-config -g redis_queue redis://redis:6379/1
bench set-config -g redis_socketio redis://redis:6379/2
bench set-config -gp socketio_port 9000
if [[ ! -f sites/"${CIPHER_SITE}"/site_config.json ]]; then
  bench new-site "$CIPHER_SITE" --mariadb-user-host-login-scope='%' \
    --admin-password "$CIPHER_ADMIN_PASSWORD" --db-root-username root \
    --db-root-password "$CIPHER_DB_ROOT_PASSWORD" --install-app erpnext --set-default
fi
bench --site "$CIPHER_SITE" set-config cipher_site_mode synthetic
bench --site "$CIPHER_SITE" set-config cipher_synthetic True --parse
bench --site "$CIPHER_SITE" set-config cipher_allow_unscanned_documents True --parse
bench --site "$CIPHER_SITE" set-config developer_mode 1 --parse
printf 'Synthetic ERPNext site is ready; install cipher_aec after its package is present.\n'
