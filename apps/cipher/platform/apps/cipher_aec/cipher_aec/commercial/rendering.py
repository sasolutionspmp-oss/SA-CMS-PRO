"""Bounded deterministic proposal PDF rendering; no source lookup or artifact write."""
import hashlib
import html
import importlib.metadata
import os
from pathlib import Path
import subprocess
import sys

from cipher_aec.api.contracts import canonical_json, digest
from cipher_aec.api.errors import DomainError

VERSIONS={"weasyprint":"68.0","pydyf":"0.12.1","fonttools":"4.67.0"}
FONTS={"regular":{"path":"/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf","sha256":"57f73e11f51999432bf7ab22ce55b6f945d5eca1bf824404cfa9ec2e3718c84e"},"bold":{"path":"/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf","sha256":"a4c5bc453ca281d90ea079e596da7ae0dfeb5777497c29ec254e76d97ff6f890"}}
PARAMETERS={"policy":"cipher.proposal.pdf.v1","page_size":"US Letter","margin_inches":"0.6","font_size_points":"9","max_pages":100,"max_bytes":10485760,"network":"disabled","html":"escaped-plain-text"}


def policy():
    """Qualification is explicit; an image/dependency/font update needs recheck."""
    try:
        if any(importlib.metadata.version(name)!=version for name,version in VERSIONS.items()):raise ValueError
        if any(hashlib.sha256(Path(value["path"]).read_bytes()).hexdigest()!=value["sha256"] for value in FONTS.values()):raise ValueError
    except (ValueError,OSError,importlib.metadata.PackageNotFoundError):
        raise DomainError("renderer_unqualified","The installed proposal renderer or fonts have not been qualified.",503) from None
    value={"renderer":"weasyprint","versions":VERSIONS,"fonts":FONTS,"parameters":PARAMETERS}
    return {**value,"fingerprint":digest(value)}


def _escape(value):
    return html.escape(str(value),quote=True).replace('\n','<br>')


def _markup(snapshot,baseline,cover,recipients):
    composition,pricing=snapshot['composition'],snapshot['pricing']
    blocks=['<h1>Proposal</h1>','<p>Company: '+_escape(snapshot['company'])+'<br>Proposal revision: '+_escape(snapshot['id'])+'<br>Valid through: '+_escape(composition['valid_till'])+'</p>']
    texts=[snapshot['company'],snapshot['id'],composition['valid_till'],cover,composition['terms']]
    if recipients:
        blocks+=['<h2>Intended recipients</h2>']
        for recipient in recipients:
            cells=(recipient['name'],recipient['email'],recipient['organization'])
            blocks+=['<p>'+_escape(cells[0])+' &lt;'+_escape(cells[1])+'&gt;<br>'+_escape(cells[2])+'</p>'];texts.extend(cells)
    if cover:blocks+=['<h2>Cover</h2><p>'+_escape(cover)+'</p>']
    for section in composition['sections']:
        blocks+=['<h2>'+_escape(section['title'])+'</h2><p>'+_escape(section['text'])+'</p>'];texts.extend((section['title'],section['text']))
    blocks+=['<h2>Price schedule ('+_escape(composition['currency'])+')</h2><table><thead><tr><th>Description</th><th>Quantity</th><th>Unit</th><th>Rate</th><th>Amount</th><th>Selection</th></tr></thead><tbody>']
    for line in pricing['lines']:
        unit=snapshot['units'][line['unit_id']]['fields']['symbol']
        selected='Included' if line['selected'] else 'Unselected alternate'
        cells=(line['description'],line['quantity'],unit,line['rate'],line['amount'],selected)
        blocks+=['<tr>'+''.join('<td>'+_escape(cell)+'</td>' for cell in cells)+'</tr>'];texts.extend(cells)
    blocks+=['</tbody></table><p><b>Total: '+_escape(composition['currency'])+' '+_escape(pricing['total'])+'</b></p>','<h2>Commercial terms</h2><p>'+_escape(composition['terms'])+'</p>']
    if baseline:
        blocks+=['<p>Accepted estimate: '+_escape(baseline['acceptance_id'])+'<br>Baseline digest: '+_escape(baseline['acceptance_digest'])+'</p>'];texts.extend((baseline['acceptance_id'],baseline['acceptance_digest']))
    css='''@font-face{font-family:Cipher;src:url(file:///usr/share/fonts/truetype/dejavu/DejaVuSans.ttf)}@font-face{font-family:Cipher;src:url(file:///usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf);font-weight:bold}@page{size:Letter;margin:0.6in}body{font:9pt Cipher;color:#111;line-height:1.3}h1{font-size:20pt}h2{font-size:12pt;break-after:avoid}p{overflow-wrap:anywhere}table{width:100%;border-collapse:collapse;table-layout:fixed;font-size:8pt}th,td{border:0.5pt solid #777;padding:4pt;vertical-align:top;overflow-wrap:anywhere}th{font-weight:bold}tr{break-inside:avoid}'''
    markup='<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Proposal</title><style>'+css+'</style></head><body>'+''.join(blocks)+'</body></html>'
    return markup,texts


def render(snapshot,baseline=None,cover='',recipients=None):
    """Returns bytes + provenance only; the governed caller authorizes exact inputs."""
    qualified=policy()
    markup,texts=_markup(snapshot,baseline,cover,recipients or [])
    payload=canonical_json({"html":markup,"texts":texts,"identifier":digest({"proposal_revision":snapshot['id'],"snapshot":digest(snapshot),"baseline":baseline,"cover":cover,"recipients":recipients or [],"policy":qualified['fingerprint']})})
    if len(payload.encode())>2*1024*1024:raise DomainError("render_limit","The proposal exceeds the bounded PDF input limit.",422)
    worker=Path(__file__).with_name('_render_worker.py')
    try:
        result=subprocess.run([sys.executable,'-I',str(worker)],input=payload.encode(),stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=35,env={'PATH':os.defpath,'LANG':'C.UTF-8','LC_ALL':'C.UTF-8','TZ':'UTC','PYTHONHASHSEED':'0'},check=False)
    except (OSError,subprocess.TimeoutExpired):
        raise DomainError("render_unavailable","The bounded proposal renderer could not complete.",503) from None
    errors={41:("unsupported_output_text","The qualified proposal font cannot represent part of the authored text.",422),42:("render_limit","The proposal exceeds the qualified PDF page or byte limit.",422)}
    if result.returncode:
        code,message,status=errors.get(result.returncode,("render_unavailable","The bounded proposal renderer could not complete.",503))
        raise DomainError(code,message,status)
    content=result.stdout
    if not content.startswith(b'%PDF-') or not 1<=len(content)<=PARAMETERS['max_bytes']:
        raise DomainError("render_integrity","The proposal renderer did not produce a bounded PDF artifact.",409)
    return content,{**qualified,"proposal_revision_digest":digest(snapshot),"baseline":baseline,"cover_digest":digest(cover),"recipients_digest":digest(recipients or []),"output_sha256":hashlib.sha256(content).hexdigest(),"output_byte_length":len(content)}
