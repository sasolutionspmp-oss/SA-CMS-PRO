import json
from frappe.model.document import Document
from cipher_aec.api.errors import DomainError
from cipher_aec.semantic_index.store import require_checkpoint_write

class CipherSemanticCorpus(Document):
    def validate(self):
        try: value=json.loads(self.data_json)
        except (TypeError,ValueError):
            raise DomainError('semantic_integrity','Supply an exact semantic checkpoint.',422) from None
        require_checkpoint_write(self,value)

    def on_trash(self):
        raise DomainError('semantic_command_required','Use bounded semantic reconciliation.',403)

    def before_rename(self,*args,**kwargs):
        raise DomainError('semantic_command_required','Semantic checkpoint identities are fixed.',403)
