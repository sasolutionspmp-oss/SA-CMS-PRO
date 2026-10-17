#!/usr/bin/env python3
"""Restore a narrow synthetic configuration allowlist while retaining quarantine."""
import json
import os
from pathlib import Path
import re
import sys

PROFILE = 'cipher.award.native.no-side-effects.v1'


def restored_settings(source):
    if not isinstance(source, dict) or source.get('cipher_site_mode') != 'synthetic' or source.get('cipher_synthetic') is not True:
        raise ValueError('The backup must declare the explicit synthetic profile.')
    result = {'cipher_site_mode': 'synthetic', 'cipher_synthetic': True,
              'pause_scheduler': True, 'cipher_execution_quarantined': True,
              'cipher_allow_unscanned_documents': source.get('cipher_allow_unscanned_documents') is True}
    if 'cipher_allow_unscanned_documents' in source and type(source['cipher_allow_unscanned_documents']) is not bool:
        raise ValueError('The synthetic document allowance must be a typed boolean.')
    if 'disable_global_search' in source:
        if type(source['disable_global_search']) is not bool:
            raise ValueError('Search suppression must be a typed boolean.')
        result['disable_global_search'] = source['disable_global_search']
    if 'cipher_award_native_profile' in source:
        if source['cipher_award_native_profile'] != PROFILE or source.get('disable_global_search') is not True:
            raise ValueError('The backup has an unsupported native profile or missing search suppression.')
        result['cipher_award_native_profile'] = PROFILE
    return result


def main(site, source_path):
    if os.environ.get('CIPHER_SYNTHETIC') != '1' or os.environ.get('CIPHER_SITE') != 'cipher.localhost':
        raise ValueError('Synthetic recovery runtime required.')
    if not re.fullmatch(r'cipher-restore(-[0-9]{14})?\.localhost', site):
        raise ValueError('Only an isolated recovery site may be configured.')
    source = Path(source_path)
    settings = restored_settings(json.loads(source.read_text()))
    target = Path('/home/frappe/frappe-bench/sites') / site / 'site_config.json'
    config = json.loads(target.read_text())
    if config.get('pause_scheduler') is not True or config.get('cipher_execution_quarantined') is not True:
        raise ValueError('The restored site must already be paused and quarantined.')
    config.update(settings)
    temporary = target.with_suffix('.cipher-recovery-pending.json')
    with temporary.open('w') as stream:
        temporary.chmod(0o600)
        stream.write(json.dumps(config, indent=2) + '\n')
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(target)
    print('Restored the allowed synthetic read settings; scheduler pause and execution quarantine remain enabled.')


if __name__ == '__main__':
    if len(sys.argv) != 3:
        raise SystemExit('Supply the isolated site and matching backup configuration snapshot.')
    main(sys.argv[1], sys.argv[2])
