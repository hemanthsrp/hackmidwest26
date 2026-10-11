FROM python:3.12-slim
WORKDIR /app
COPY microservices/volatility-surface-builder /build/volatility-surface-builder
RUN pip install --no-cache-dir '/build/volatility-surface-builder[live]' && useradd --system --uid 10001 app
USER app
EXPOSE 8002
CMD ["uvicorn", "vol_surface_builder.api:app", "--host", "0.0.0.0", "--port", "8002"]
