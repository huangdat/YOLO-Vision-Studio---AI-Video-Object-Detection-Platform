# Default target (last stage, "dev"): the Vite development server used by compose.yaml.
# "production": the static build served by unprivileged nginx (compose.production.yaml).
FROM node:24-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM deps AS build
COPY . .
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.28-alpine AS production
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=5 \
    CMD wget --quiet --spider http://127.0.0.1:8080/ || exit 1

FROM deps AS dev
COPY . .
EXPOSE 5173
CMD ["npm", "run", "dev"]
