FROM node:22.16.0-bookworm-slim AS builder
WORKDIR /app

COPY package.json package-lock.json .npmrc ./
RUN npm config set registry https://registry.npmjs.org/ \
    && npm ci --ignore-scripts --no-audit --no-fund

COPY tsconfig.json vite.config.ts eslint.config.js index.html ./
COPY src/ src/

ARG VITE_SUPABASE_URL
ARG VITE_SUPABASE_PUBLISHABLE_KEY
ARG VITE_API_URL
ARG VITE_PUBLIC_APP_URL
ENV VITE_SUPABASE_URL=$VITE_SUPABASE_URL
ENV VITE_SUPABASE_PUBLISHABLE_KEY=$VITE_SUPABASE_PUBLISHABLE_KEY
ENV VITE_API_URL=$VITE_API_URL
ENV VITE_PUBLIC_APP_URL=$VITE_PUBLIC_APP_URL

RUN npm run build

FROM nginx:alpine
RUN rm -f /etc/nginx/conf.d/default.conf
COPY frontend/nginx.conf.template /etc/nginx/templates/mulyankan.conf.template
COPY --from=builder /app/dist /usr/share/nginx/html
EXPOSE 80

HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
  CMD wget -qO- http://127.0.0.1/healthz || exit 1
