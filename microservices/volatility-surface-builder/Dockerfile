FROM python:3.15-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928
WORKDIR /app
# Exact third-party versions, the same ones CI tests (scripts/lock-python.sh).
COPY requirements/python.lock /build/python.lock
COPY microservices/volatility-surface-builder /build/volatility-surface-builder
RUN pip install --no-cache-dir -c /build/python.lock '/build/volatility-surface-builder[live]' && useradd --system --uid 10001 app
USER app
EXPOSE 8002
CMD ["uvicorn", "vol_surface_builder.api:app", "--host", "0.0.0.0", "--port", "8002"]
