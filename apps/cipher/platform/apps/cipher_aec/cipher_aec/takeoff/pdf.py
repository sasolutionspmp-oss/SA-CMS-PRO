"""Isolated, bounded page metadata derived from authorized PDF bytes."""
import json
import subprocess
import sys

from cipher_aec.api.errors import DomainError
from .geometry import COORDINATES, fail, page_frame


def page_geometry(content, page):
    if type(content) is not bytes or not content.startswith(b"%PDF-") or len(content) > 10 * 1024 * 1024 or type(page) is not int or not 1 <= page <= 200:
        fail("Calibrated geometry requires an actual supported stored PDF page.", "source", "unsupported_drawing")
    try:
        parsed = subprocess.run([sys.executable, "-I", "-c", WORKER, str(page)], input=content,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=15, check=False)
        if parsed.returncode or len(parsed.stdout) > 4096:
            raise ValueError
        frame = json.loads(parsed.stdout)
        page_frame(frame)
        return frame
    except (OSError, subprocess.TimeoutExpired, ValueError, TypeError, KeyError, DomainError):
        fail("PDF page metadata is unavailable or outside the supported finite planar policy.", "source", "unsupported_drawing")


WORKER = r'''
import io,json,sys
try:
    import resource
    resource.setrlimit(resource.RLIMIT_AS,(384*1024*1024,384*1024*1024))
    resource.setrlimit(resource.RLIMIT_CPU,(10,10))
    from pypdf import PdfReader,__version__
    reader=PdfReader(io.BytesIO(sys.stdin.buffer.read(10*1024*1024+1)),strict=True)
    if reader.is_encrypted or len(reader.pages)>200:
        raise ValueError()
    page=reader.pages[int(sys.argv[1])-1]
    from decimal import Decimal
    rotation=Decimal(str(page.get('/Rotate',0)))
    if not rotation.is_finite() or rotation != rotation.to_integral_value() or rotation not in (0,90,180,270):
        raise ValueError()
    print(json.dumps({'coordinate_system':'pdf-user-space-v1',
        'media_box':[str(v) for v in page.mediabox],
        'crop_box':[str(v) for v in page.cropbox],
        'rotate':int(rotation),
        'user_unit':str(page.get('/UserUnit',1)),
        'parser':'pypdf-'+__version__+':cipher-page-metadata-v1'}))
except Exception:
    sys.exit(2)
'''
