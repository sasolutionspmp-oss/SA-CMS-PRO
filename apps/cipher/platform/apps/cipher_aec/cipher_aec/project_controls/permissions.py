"""Public native projections are closed; canonical readers enforce exact sources."""
def query_conditions(user=None):return '1=0'
def has_permission(doc,ptype='read',user=None,**kwargs):return False
