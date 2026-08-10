# Misen Companion API.
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

COPY alembic.ini ./
COPY alembic ./alembic
COPY scripts ./scripts
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Non-root. The uid is fixed and high to avoid colliding with a host user, and
# /data is chowned because it is a bind mount the container must write to.
RUN useradd --system --uid 10001 --create-home misen \
    && mkdir -p /data \
    && chown -R misen:misen /data /app
USER misen

EXPOSE 8000

# No curl in the image, so the check is a Python one-liner. Compose declares an
# equivalent check; this one covers `docker run` outside compose.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status == 200 else 1)"

# The entrypoint runs migrations first, then hands off to CMD. Overriding CMD
# (to run provision.py, say) still gets a migrated database.
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
