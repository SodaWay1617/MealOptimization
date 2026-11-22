FROM node:22-alpine AS frontend
WORKDIR /build
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.11-slim
WORKDIR /app
COPY meal-planner/web-requirements.txt ./
RUN pip install --no-cache-dir -r web-requirements.txt
COPY meal-planner/app ./app
COPY meal-planner/config/categories.yaml ./config/categories.yaml
COPY --from=frontend /build/dist /web
ENV WEB_DIST=/web RECIPES_DIR=/recipes PYTHONDONTWRITEBYTECODE=1
CMD ["waitress-serve", "--host=0.0.0.0", "--port=8080", "--call", "app.web.server:create_app"]
