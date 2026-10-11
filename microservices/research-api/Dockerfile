FROM python:3.12-slim
WORKDIR /app
COPY microservices/research-api/pyproject.toml /app/research-api/pyproject.toml
COPY microservices/research-api/src /app/research-api/src
COPY microservices/decision-maker/pyproject.toml /app/decision-maker/pyproject.toml
COPY microservices/decision-maker/src /app/decision-maker/src
RUN pip install --no-cache-dir "/app/research-api" "/app/decision-maker[pg,agent]" \
    && useradd --system --uid 10001 app
USER app
EXPOSE 8000
CMD ["uvicorn", "research_api.app:app", "--host", "0.0.0.0", "--port", "8000"]
