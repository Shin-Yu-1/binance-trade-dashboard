# syntax=docker/dockerfile:1

FROM node:20-slim AS frontend-build
WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS backend-base
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
COPY backend/pyproject.toml ./
COPY backend/app ./app
COPY backend/alembic ./alembic
COPY backend/alembic.ini ./
RUN pip install --upgrade pip && pip install -e .[dev]

FROM backend-base AS test
COPY backend/tests ./tests
CMD ["pytest", "-v"]

FROM backend-base AS runtime
COPY --from=frontend-build /frontend/dist ./static
COPY backend/entrypoint.sh ./entrypoint.sh
RUN chmod +x entrypoint.sh
EXPOSE 8000
ENTRYPOINT ["./entrypoint.sh"]
