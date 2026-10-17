from frappe.model.document import Document
from cipher_aec.ricky.company_draft_save import validate_document
from cipher_aec.ricky.company_draft_save_contracts import refuse

class CipherRickyDraftSave(Document):
    def validate(self):
        validate_document(self)

    def on_trash(self):
        refuse("Draft-save application history cannot be deleted.", "immutable_record")

    def before_rename(self, *args, **kwargs):
        refuse("Draft-save application history cannot be renamed.", "immutable_record")
