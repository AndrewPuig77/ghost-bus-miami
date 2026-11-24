# Build the static app with Node, then serve it with Caddy, which also forwards
# /api and /ws to the FastAPI container. Only the small Caddy stage ships.
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM caddy:2-alpine
COPY Caddyfile /etc/caddy/Caddyfile
COPY --from=build /app/dist /srv
