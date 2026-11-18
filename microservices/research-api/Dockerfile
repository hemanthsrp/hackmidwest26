FROM python:3.15-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928
WORKDIR /app
# Exact third-party versions, the same ones CI tests (scripts/lock-python.sh).
COPY requirements/python.lock /app/python.lock
COPY microservices/research-api/pyproject.toml /app/research-api/pyproject.toml
COPY microservices/research-api/src /app/research-api/src
COPY microservices/decision-maker/pyproject.toml /app/decision-maker/pyproject.toml
COPY microservices/decision-maker/src /app/decision-maker/src
COPY microservices/jev-tool /app/jev-tool
RUN pip install --no-cache-dir -c /app/python.lock "/app/research-api" "/app/decision-maker[pg,agent]" /app/jev-tool \
    && useradd --system --uid 10001 app
USER app
EXPOSE 8000
CMD ["uvicorn", "research_api.app:app", "--host", "0.0.0.0", "--port", "8000"]
