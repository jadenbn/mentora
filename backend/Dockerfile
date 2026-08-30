# Mentora API. Python 3.11+ is required for asyncio.timeout; 3.12 matches the
# interpreter the team develops against.
FROM python:3.12-slim

# PYTHONDONTWRITEBYTECODE keeps container-built .pyc files out of the bind
# mount, where they would collide with the host's own __pycache__.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Copied before the source so a code edit does not reinstall dependencies.
COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY . .

EXPOSE 8000

# 0.0.0.0 binds beyond loopback so the published port reaches the host. This is
# the container's own network namespace, not the machine's — Compose decides
# what is actually exposed, via the ports mapping.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
