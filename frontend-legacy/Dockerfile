##
# Multi-stage:
# - dev: Vite dev server (for local docker-compose)
# - build: production build to /dist
# - runtime: nginx serving static assets + optional /api reverse proxy (same-origin)
##

FROM node:20-alpine AS dev
WORKDIR /app
COPY package*.json ./
RUN npm ci --no-audit --no-fund --legacy-peer-deps
COPY . .
EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]

FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci --no-audit --no-fund --legacy-peer-deps
COPY . .
RUN npm run build

FROM nginx:1.27-alpine AS runtime

# Railway will inject PORT; default to a high port so we can run as non-root.
ENV PORT=8080 \
    API_PROXY_TARGET=http://api:8000

# Provide an unprivileged nginx.conf so we can run as non-root.
COPY nginx/nginx.conf /etc/nginx/nginx.conf

# Nginx official image will envsubst templates in /etc/nginx/templates/*.template
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 8080

# Prepare writable dirs for the unprivileged user.
RUN mkdir -p /etc/nginx/templates /etc/nginx/conf.d && \
    chown -R nginx:nginx /etc/nginx /usr/share/nginx/html /var/cache/nginx

# Run as non-root (requires PORT >= 1024)
USER nginx

CMD ["nginx", "-g", "daemon off;"]
