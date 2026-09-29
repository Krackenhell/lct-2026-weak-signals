FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
# Зеркало npm для серверов, где registry.npmjs.org недоступен; целостность проверяется по package-lock.json
ARG NPM_REGISTRY=https://registry.npmjs.org/
RUN npm ci --no-audit --no-fund --registry="$NPM_REGISTRY"
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
