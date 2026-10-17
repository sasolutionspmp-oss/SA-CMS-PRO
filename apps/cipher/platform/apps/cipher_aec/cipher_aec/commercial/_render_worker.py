"""Isolated, resource-bounded renderer. No Frappe, database, source fetch or network."""
import hashlib
import json
from pathlib import Path
import resource
import sys
from urllib.parse import urlparse,unquote

resource.setrlimit(resource.RLIMIT_AS,(512*1024*1024,512*1024*1024))
resource.setrlimit(resource.RLIMIT_CPU,(25,25))
resource.setrlimit(resource.RLIMIT_FSIZE,(12*1024*1024,12*1024*1024))
resource.setrlimit(resource.RLIMIT_NOFILE,(64,64))

value=json.loads(sys.stdin.buffer.read(2*1024*1024+1))
fonts=('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf','/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf')
from fontTools.ttLib import TTFont
coverage=[set(TTFont(path).getBestCmap()) for path in fonts]
allowed=coverage[0]&coverage[1]
if any(ord(character) not in allowed and character not in '\n\r\t' for text in value['texts'] for character in str(text)):
    sys.exit(41)
forbidden=[]
def fetch(url,*args,**kwargs):
    parsed=urlparse(url)
    path=unquote(parsed.path)
    if parsed.scheme!='file' or parsed.netloc or path not in fonts:
        forbidden.append(url)
        raise ValueError('Only qualified local font bytes may be loaded')
    return {'string':Path(path).read_bytes(),'mime_type':'font/ttf','redirected_url':url}

from weasyprint import HTML
from weasyprint.text.fonts import FontConfiguration
rendered=HTML(string=value['html'],url_fetcher=fetch).render(font_config=FontConfiguration())
if len(rendered.pages)>100:sys.exit(42)
content=rendered.write_pdf(pdf_identifier=value['identifier'].encode('ascii'))
if forbidden:sys.exit(43)
if len(content)>10485760:sys.exit(42)
sys.stdout.buffer.write(content)
