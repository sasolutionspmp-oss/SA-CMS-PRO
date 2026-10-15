#!/usr/bin/env bash
set -euo pipefail
cd /home/frappe/frappe-bench
[[ "${CIPHER_SYNTHETIC:-}" == 1 ]] || { echo 'Synthetic development installation only.' >&2; exit 2; }
env/bin/pip install -e apps/cipher_aec
python - <<'PY'
from pathlib import Path
p = Path('sites/apps.txt')
apps = p.read_text().splitlines() if p.exists() else ['frappe', 'erpnext']
if 'cipher_aec' not in apps:
    apps.append('cipher_aec')
p.write_text('\n'.join(apps) + '\n')
assets = Path('sites/assets')
if not assets.exists():
    assets.symlink_to(Path('/home/frappe/frappe-bench/assets'))
PY
bench --site "$CIPHER_SITE" install-app cipher_aec
bench --site "$CIPHER_SITE" migrate
