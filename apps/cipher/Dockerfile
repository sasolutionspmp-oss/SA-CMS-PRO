# Cipher synthetic prototype - container for tests and the owner console.
# Standard library only: no package installation, no network at build or run time.
FROM python:3.12-slim

WORKDIR /workspace
COPY apps/cipher /workspace/apps/cipher
ENV PYTHONPATH=/workspace \
    PYTHONDONTWRITEBYTECODE=1 \
    CIPHER_DB=/workspace/data/cipher.sqlite \
    CIPHER_PORT=8765
RUN mkdir -p /workspace/data && python -m apps.cipher test
EXPOSE 8765
VOLUME ["/workspace/data"]
CMD ["python", "-m", "apps.cipher", "serve", "--host", "0.0.0.0", "--demo"]
