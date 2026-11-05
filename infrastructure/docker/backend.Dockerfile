# (unverified: Docker was not available in the build environment)
FROM node:22-alpine AS ui
WORKDIR /ui
COPY frontend/package.json ./
RUN npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
RUN useradd --create-home --uid 10001 autolink
WORKDIR /app
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt gunicorn==23.0.0
COPY backend/ ./
COPY --from=ui /ui/dist /srv/dashboard
ENV AUTOLINK_FRONTEND_DIST=/srv/dashboard
USER autolink
EXPOSE 8000
HEALTHCHECK CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/health')"
CMD ["sh", "-c", "python -m app.cli migrate && exec gunicorn -w 1 --threads 8 -b 0.0.0.0:8000 'app:create_app()'"]
