# Cipher synthetic prototype - container for tests and the owner console.
# Standard library only: no package installation, no network at build or run time.
#
#   docker build -f apps/cipher/Dockerfile -t cipher-prototype .
#   docker run --rm -e CIPHER_TOKEN=<16+ char secret> -p 127.0.0.1:8765:8765 -v cipher-data:/workspace/data cipher-prototype
#   then open http://127.0.0.1:8765/?token=<secret> once (sets an HttpOnly session cookie)
#
# The server inside the container must listen on 0.0.0.0 for the port mapping, so it
# refuses to start without CIPHER_TOKEN.  Publish on 127.0.0.1 unless you mean to share it.
FROM python:3.12-slim

WORKDIR /workspace
COPY apps/cipher /workspace/apps/cipher
ENV PYTHONPATH=/workspace \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CIPHER_DB=/workspace/data/cipher.sqlite \
    CIPHER_PORT=8765
# COPY preserves restrictive modes from private checkouts. The server user
# needs to read application files and traverse their directories.
RUN chmod -R a+rX /workspace/apps \
 && python -m apps.cipher test \
 && useradd --system --uid 10001 --home-dir /workspace --shell /usr/sbin/nologin cipher \
 && mkdir -p /workspace/data \
 && chown -R cipher:cipher /workspace/data
USER cipher
EXPOSE 8765
VOLUME ["/workspace/data"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8765/api/health', timeout=4).status == 200 else 1)"]
CMD ["python", "-m", "apps.cipher", "serve", "--host", "0.0.0.0", "--demo"]
