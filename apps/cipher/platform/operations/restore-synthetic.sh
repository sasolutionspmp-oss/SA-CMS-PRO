#!/usr/bin/env bash
# Inside the runtime. Restore only into a dedicated isolated, quarantined site.
set -euo pipefail
[[ "${CIPHER_SYNTHETIC:-}" == 1 && "${CIPHER_SITE:-}" == cipher.localhost ]] || exit 2
cd /home/frappe/frappe-bench
restore_site="${CIPHER_RESTORE_SITE:-cipher-restore.localhost}"
[[ "$restore_site" =~ ^cipher-restore(-[0-9]{14})?\.localhost$ ]] || { echo 'Invalid isolated restore target.' >&2; exit 2; }
[[ ! -d "sites/$restore_site" ]] || { echo 'Restore verification site already exists; refusing overwrite.' >&2; exit 2; }
backup_prefix="${1:?Supply the exact backup filename prefix, without directory or suffix}"
[[ "$backup_prefix" =~ ^[0-9]{8}_[0-9]{6}-cipher_localhost$ ]] || exit 2
backup_base="sites/cipher.localhost/private/backups/$backup_prefix"
for suffix in database.sql.gz files.tgz private-files.tgz site_config_backup.json; do
  [[ -f "$backup_base-$suffix" ]] || { echo 'Incomplete backup set.' >&2; exit 2; }
done
bench new-site "$restore_site" --mariadb-user-host-login-scope='%' \
  --admin-password "$CIPHER_ADMIN_PASSWORD" --db-root-username root --db-root-password "$CIPHER_DB_ROOT_PASSWORD"
bench --site "$restore_site" set-config pause_scheduler True --parse
bench --site "$restore_site" set-config cipher_execution_quarantined True --parse
bench --site "$restore_site" set-config cipher_site_mode synthetic
bench --site "$restore_site" restore "$backup_base-database.sql.gz" \
  --with-public-files "$backup_base-files.tgz" --with-private-files "$backup_base-private-files.tgz" \
  --db-root-username root --db-root-password "$CIPHER_DB_ROOT_PASSWORD" --force
python - "$backup_base-site_config_backup.json" "$restore_site" <<'PY'
import json
import sys
from pathlib import Path
source = json.loads(Path(sys.argv[1]).read_text())
target = Path('sites') / sys.argv[2] / 'site_config.json'
config = json.loads(target.read_text())
if source.get('encryption_key'):
    config['encryption_key'] = source['encryption_key']
config.update(pause_scheduler=True, cipher_execution_quarantined=True, cipher_site_mode='synthetic')
target.write_text(json.dumps(config, indent=2)+'\n')
target.chmod(0o600)
PY
printf 'Backup restored into isolated %s with scheduler paused and execution quarantined.\n' "$restore_site"
