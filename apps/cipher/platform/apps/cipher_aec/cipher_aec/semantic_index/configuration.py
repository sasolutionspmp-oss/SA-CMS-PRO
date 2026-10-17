"""Server-owned opt-in configuration. No guessed model, URL or dimensions."""
from cipher_aec.api.errors import DomainError
from .providers import OllamaEmbedder,QdrantIndex

KEY='cipher_semantic_index'
FIELDS={'enabled','ollama_endpoint','model_tag','model_digest','dimensions','embedding_protocol',
        'qdrant_endpoint','collection','index_protocol','timeout_seconds','max_body_bytes'}

def clients(config):
    if not isinstance(config,dict) or config.get('enabled') is not True:
        raise DomainError('semantic_unavailable','Semantic search is not configured for this site.',503)
    if set(config) not in (FIELDS,FIELDS|{'qdrant_api_key'}):
        raise DomainError('semantic_unavailable','The semantic provider configuration is incomplete.',503)
    # Keys and credentials are never accepted in service/RPC request bodies.
    embedder=OllamaEmbedder(config['ollama_endpoint'],config['model_tag'],config['model_digest'],config['dimensions'],
                          protocol=config['embedding_protocol'],timeout=config['timeout_seconds'],max_body=config['max_body_bytes'])
    index=QdrantIndex(config['qdrant_endpoint'],config['collection'],config['dimensions'],
                     protocol=config['index_protocol'],timeout=config['timeout_seconds'],max_body=config['max_body_bytes'],
                     api_key=config.get('qdrant_api_key'))
    return embedder,index

def configuration_status(config):
    try: clients(config)
    except DomainError: return {'status':'unavailable','connected_qualification':False}
    return {'status':'configured_not_probed','connected_qualification':False}

def service(*,durable=False):
    import frappe
    from cipher_aec.document_control.semantic_source import SourceAdapter
    from .store import FrappeStore
    from .service import SemanticService
    embedder,index=clients(frappe.conf.get(KEY))
    return SemanticService(FrappeStore(durable=durable),SourceAdapter(),embedder,index)
