FROM python:3.11.15-slim-trixie@sha256:db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/srv/recpro

WORKDIR /srv/recpro

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libc6-dev

COPY backend/requirements-g1.lock /opt/recpro/requirements-g1.lock
RUN python -m pip install --no-cache-dir --require-hashes \
    -r /opt/recpro/requirements-g1.lock

COPY backend /srv/recpro/backend
COPY contracts/config /srv/recpro/contracts/config

RUN useradd --create-home --shell /usr/sbin/nologin recpro
USER recpro

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=6 \
    CMD ["python", "-c", "from urllib.request import urlopen; urlopen('http://127.0.0.1:8000/api/v1/health/live', timeout=2).read()"]

CMD ["python", "-m", "uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
