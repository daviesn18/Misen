# Misen MCP server.
#
# Multi-arch by construction: python:3.13-slim publishes amd64 and arm64, so
# this builds unchanged on an x86 VPS or an Oracle Ampere box.

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first, so a source-only change does not reinstall the world.
COPY pyproject.toml ./
COPY app ./app
RUN pip install .

# Non-root, and no writable state at all — this service holds no database and
# no secrets of its own beyond the Mealie token it is given at runtime.
RUN useradd --system --uid 10002 --create-home misen
USER misen

EXPOSE 8001

# No curl in the image, and http.client is used rather than urllib because it
# does not raise on a 4xx. The MCP endpoint answers 401 without a token, and a
# 401 means the process is serving perfectly well — a check that treated it as
# a failure would restart a healthy container forever.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import http.client,sys; c=http.client.HTTPConnection('127.0.0.1',8001,timeout=3); c.request('GET','/mcp'); sys.exit(0 if c.getresponse().status else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
