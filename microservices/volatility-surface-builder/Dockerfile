FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
WORKDIR /app
# Exact third-party versions, the same ones CI tests (scripts/lock-python.sh).
COPY requirements/python.lock /build/python.lock
COPY microservices/volatility-surface-builder /build/volatility-surface-builder
RUN pip install --no-cache-dir -c /build/python.lock '/build/volatility-surface-builder[live]' && useradd --system --uid 10001 app
USER app
EXPOSE 8002
CMD ["uvicorn", "vol_surface_builder.api:app", "--host", "0.0.0.0", "--port", "8002"]
