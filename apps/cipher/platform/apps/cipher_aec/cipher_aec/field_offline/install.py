"""Private native access; explicit indexes installed only by local composition."""
def query_denied(*args,**kwargs):return '1=0'
def permission_denied(*args,**kwargs):return False

def ensure_indexes():
    import frappe
    frappe.db.add_index('Cipher Field Offline Capture',['company','project','owner_person','capture_id'],index_name='cipher_offline_scope_capture')
    frappe.db.add_index('Cipher Field Offline Event',['company','project','owner_person','capture_id'],index_name='cipher_offline_scope_event')
