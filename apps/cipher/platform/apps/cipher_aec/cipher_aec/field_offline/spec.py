"""Exact FLD-01 command bytes; offline metadata never alters that payload."""
from copy import deepcopy
from cipher_aec.api.contracts import digest

def business_request(envelope):
    command=envelope['command']; action=command['action']; family=command['family']
    payload={k:deepcopy(command[k]) for k in ('family','definition','photos','quantities')}
    if action=='revise':
        payload.update({k:command[k] for k in ('record_id','expected_version','amendment_reason')})
    name='field.'+family+'.'+action+'.v1'
    checksum=digest({'command':name,'company':envelope['company'],'project':envelope['project'],'payload':payload})
    return name,payload,checksum
