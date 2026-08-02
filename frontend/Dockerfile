FROM node:24.18.0-alpine3.24@sha256:a0b9bf06e4e6193cf7a0f58816cc935ff8c2a908f81e6f1a95432d679c54fbfd AS build

WORKDIR /workspace

COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts

COPY index.html tsconfig.json vite.config.ts vitest.config.ts ./
COPY src ./src
COPY scripts ./scripts
ENV RECPRO_BUILD_RUN_ID=container-image
RUN npm run build

FROM nginx:1.30.4-alpine@sha256:97d490c12ba55b4946b01546d1c3ed324e8d41ab1c9fcb2a616aa470620e5b46 AS runtime

COPY nginx/nginx.conf /etc/nginx/nginx.conf
COPY nginx/default.conf /etc/nginx/conf.d/default.conf
COPY --chown=nginx:nginx --from=build /workspace/dist/container-image /srv/recpro

EXPOSE 8080

USER nginx

ENTRYPOINT []
CMD ["nginx", "-g", "daemon off;"]
