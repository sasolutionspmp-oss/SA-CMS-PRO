"""Run with the bench Python inside the container; no credential output."""
import hashlib
import json
import uuid
import frappe
import os
import re
from pathlib import Path
os.chdir("/home/frappe/frappe-bench/sites")

site = os.environ.get('CIPHER_RESTORE_SITE', 'cipher-restore.localhost')
assert re.fullmatch(r'cipher-restore(-[0-9]{14})?\.localhost', site), 'Invalid isolated restore target'
frappe.init(site=site, sites_path='/home/frappe/frappe-bench/sites')
frappe.connect()
try:
    assert frappe.conf.cipher_execution_quarantined
    assert frappe.conf.pause_scheduler
    backup_prefix = os.environ.get('CIPHER_RESTORE_BACKUP_PREFIX')
    key_preserved = None
    if backup_prefix:
        assert re.fullmatch(r'[0-9]{8}_[0-9]{6}-cipher_localhost', backup_prefix)
        backup_config = Path('/home/frappe/frappe-bench/sites/cipher.localhost/private/backups') / (backup_prefix + '-site_config_backup.json')
        saved_config = json.loads(backup_config.read_text())
        key_preserved = bool(saved_config.get('encryption_key')) and saved_config['encryption_key'] == frappe.conf.encryption_key
        assert key_preserved, 'Snapshot encryption key was not preserved'
    frappe.set_user('morgan@cipher.example')
    from cipher_aec.projects.service import read_project, create_task
    from cipher_aec.api.errors import DomainError
    from cipher_aec.documents.storage import FrappeFileStorage
    from cipher_aec.integrations.outbox import dispatch_pending
    company = 'Cipher Synthetic Company'
    project = frappe.db.get_value('Project', {'project_name': 'Synthetic bridge rehabilitation'}, 'name')
    result = read_project(company, project)
    count = frappe.db.count('Task', {'project': project})
    try:
        create_task(company, project, str(uuid.uuid4()), result['version'], 'Restore quarantine probe')
        raise AssertionError('Restored site admitted a new effect')
    except DomainError as exc:
        denial = exc.code
        assert denial == 'execution_quarantined', denial
    assert frappe.db.count('Task', {'project': project}) == count
    assert dispatch_pending() == 0
    revisions = frappe.get_all('Cipher Document Revision', filters={'project': project}, fields=['name','sha256','byte_length','storage_reference'])
    artifacts = []
    for row in revisions:
        content = FrappeFileStorage().read(row.storage_reference, row.sha256, row.byte_length)
        assert hashlib.sha256(content).hexdigest() == row.sha256
        artifacts.append({'revision': row.name, 'sha256': row.sha256, 'bytes': len(content)})
    assert artifacts, 'No stored artifact was restored'
    print(json.dumps({'site':site, 'result':'passed', 'project':project,
        'restored_task_count':count, 'new_effect_denied':denial, 'dispatcher_effects':0,
        'scheduler_paused':True, 'artifacts':artifacts, 'backup_prefix':backup_prefix,
        'snapshot_encryption_key_preserved':key_preserved}, indent=2))
finally:
    frappe.db.rollback()
    frappe.destroy()
