# syntax=docker/dockerfile:1.7
FROM node:24-alpine AS base
WORKDIR /app

# ---------- desenvolvimento: Vite com hot reload (código montado por volume) ----------
FROM base AS dev
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund
COPY . .
ENV CHOKIDAR_USEPOLLING=true
EXPOSE 5173
CMD ["sh", "-c", "npm ci --no-audit --no-fund --prefer-offline >/dev/null 2>&1; npm run dev"]

# ---------- build de produção ----------
FROM base AS build
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund
COPY . .
RUN npm run build

# ---------- produção: Nginx servindo o build e fazendo proxy da API ----------
FROM nginx:1.31.6-alpine AS prod
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
RUN chown -R nginx:nginx /usr/share/nginx/html /var/cache/nginx /var/run /var/log/nginx \
    && sed -i 's/^user .*;//' /etc/nginx/nginx.conf \
    && sed -i 's#pid .*;#pid /tmp/nginx.pid;#' /etc/nginx/nginx.conf
USER nginx
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s CMD wget -qO- http://127.0.0.1:8080/ >/dev/null || exit 1
