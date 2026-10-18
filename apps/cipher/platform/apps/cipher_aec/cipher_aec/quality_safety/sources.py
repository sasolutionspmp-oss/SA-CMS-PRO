"""Reuse FLD-01's bounded canonical-byte and current-rights admission."""
from cipher_aec.field.sources import resolve, mapped
from cipher_aec.api.errors import DomainError

def references(value):
    return [*value.get('evidence',[]),*[s for row in value.get('closure',[]) for s in row['evidence']]]

def verify(values,company,project,actor,*,lock=False,new_use=False):
    refs=[source for value in values for source in references(value)]
    resolved=resolve(company,project,refs,actor,lock=lock,new_use=new_use)
    if any(row!=mapped(row,resolved) for row in refs):
        raise DomainError('quality_safety_integrity','Original evidence metadata differs from its canonical bytes.',409)
    return resolved
