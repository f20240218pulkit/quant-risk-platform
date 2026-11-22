FROM node:22-bookworm-slim AS frontend
WORKDIR /build
COPY web/package*.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY src/ src/
RUN pip install --no-cache-dir '.[product]'
COPY alembic.ini ./
COPY migrations/ migrations/
COPY --from=frontend /build/dist /app/web/dist
RUN useradd --create-home --uid 10001 workbench
USER workbench
CMD ["python", "-m", "uvicorn", "src.product.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8001"]
