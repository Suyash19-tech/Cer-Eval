FROM node:22-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# next.config rewrites are resolved at build time, so the backend URL is a build arg.
ARG HAL_BACKEND_URL=http://backend:8000
ENV HAL_BACKEND_URL=$HAL_BACKEND_URL NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:22-slim
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1
COPY --from=build /app ./
EXPOSE 3000
CMD ["npm", "run", "start"]
