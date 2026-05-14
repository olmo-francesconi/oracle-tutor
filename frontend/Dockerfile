##
# Multi-stage:
# - dev: Vite dev server (for local docker-compose)
# - build: production build to /dist
# - runtime: nginx serving static assets + optional /api reverse proxy (same-origin)
##

FROM node:20-alpine AS dev
WORKDIR /app
COPY package*.json ./
RUN npm ci --no-audit --no-fund
COPY . .
EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]

FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM nginx:1.27-alpine AS runtime

ENV PORT=8080 \
    API_PROXY_TARGET=http://api:8000 \
    NGINX_RESOLVER=[fd12::10] \
    ADMIN_HOST=admin.oracletutor.org

COPY nginx/nginx.conf /etc/nginx/nginx.conf
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY nginx/proxy_params /etc/nginx/proxy_params
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 8080

RUN mkdir -p /etc/nginx/templates /etc/nginx/conf.d && \
    chown -R nginx:nginx /etc/nginx /usr/share/nginx/html /var/cache/nginx

USER nginx

CMD ["nginx", "-g", "daemon off;"]
