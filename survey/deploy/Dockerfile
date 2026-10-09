FROM node:22-bookworm-slim AS frontend
WORKDIR /build
COPY survey/frontend/package.json survey/frontend/package-lock.json ./
RUN npm ci
COPY survey/frontend/ ./
RUN npm test && npm run build

FROM python:3.12-slim-bookworm
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY survey/deploy/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY survey/backend/*.py /app/survey/backend/
COPY survey/config/ /app/survey/config/
COPY survey/deploy/study/ /app/survey/deploy/study/
COPY survey/deploy/start.py /app/survey/deploy/start.py
COPY --from=frontend /build/dist/ /app/survey/frontend/dist/
RUN useradd --create-home survey
USER survey
CMD ["python", "survey/deploy/start.py"]
