"""Private capability for actual rendered bytes; reads never establish this context."""
from contextlib import contextmanager
from contextvars import ContextVar
import json
from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError

_active = ContextVar("cipher_exact_prepared_output_write",default=None)


def _refuse():
    raise DomainError("preparation_required","Generated documents require the exact authorized rendered-output preparation.",403)


@contextmanager
def _writing_output(*,company,proposal_revision,input_digest,renderer_fingerprint,source_sha256,byte_length,generation_digest):
    if _active.get() is not None:
        _refuse()
    value={"company":company,"proposal_revision":proposal_revision,"input_digest":input_digest,"renderer_fingerprint":renderer_fingerprint,
        "source_sha256":source_sha256,"byte_length":byte_length,"generation_digest":generation_digest,"parent":None,"revision":None}
    token=_active.set(value)
    try:yield
    finally:_active.reset(token)


def _claims(row):
    from .provenance import binding
    value=binding(row)
    if value is None:return None
    held=_active.get()
    if held is None or (row.get("company"),row.get("producer_reference"),row.get("producer_input_digest"),value["renderer"].get("fingerprint")) != (held["company"],held["proposal_revision"],held["input_digest"],held["renderer_fingerprint"]):
        _refuse()
    return held


def _bind_parent(row):
    held=_claims(row)
    if held is None or held["parent"] is not None:
        _refuse()
    held["parent"]=row["name"]


def _bind_revision(revision_id):
    held=_active.get()
    if held is None or held["parent"] is None or held["revision"] is not None:
        _refuse()
    held["revision"]=revision_id


def require_preparation(row,*,revision=False):
    held=_claims(row)
    if held is None:return
    if held["parent"] is None:
        _refuse()
    if revision:
        if row.get("document")!=held["parent"] or row.get("name")!=held["revision"] or row.get("sha256")!=held["source_sha256"] or row.get("byte_length")!=held["byte_length"]:
            _refuse()
        try:
            value=json.loads(row.get("generation_json"))
            if digest(value)!=held["generation_digest"] or value["output_sha256"]!=held["source_sha256"] or value["output_byte_length"]!=held["byte_length"] or value["input_digest"]!=held["input_digest"] or value["fingerprint"]!=held["renderer_fingerprint"]:
                _refuse()
        except (ValueError,TypeError,KeyError):
            _refuse()
    elif row.get("name")!=held["parent"] or row.get("revision_number") not in (0,1) or row.get("current_revision") not in (None,held["revision"]):
        _refuse()
