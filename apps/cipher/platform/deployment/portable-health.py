#!/usr/bin/env python3
"""Ready means the UI and actual Frappe ping route both answer locally."""
import json
from urllib.request import Request, urlopen

with urlopen('http://127.0.0.1:8080/', timeout=3) as response:
    if response.status != 200:
        raise SystemExit(1)
request = Request('http://127.0.0.1:8000/api/method/ping', headers={'Host': 'cipher.localhost'})
with urlopen(request, timeout=3) as response:
    if json.load(response).get('message') != 'pong':
        raise SystemExit(1)
