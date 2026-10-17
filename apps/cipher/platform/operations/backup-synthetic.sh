#!/usr/bin/env bash
set -euo pipefail
# Inside the runtime: only the explicit synthetic development site is supported.
[[ "${CIPHER_SYNTHETIC:-}" == 1 && "${CIPHER_SITE:-}" == cipher.localhost ]] || { echo 'Synthetic backup profile required.' >&2; exit 2; }
cd /home/frappe/frappe-bench
bench --site "$CIPHER_SITE" backup --with-files --compress
