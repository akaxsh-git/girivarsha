# Phase 1 skeleton Dockerfile — untested (no docker daemon in the sandbox
# this was built in; see docker-compose.yml note). Simple dev-server image
# for now; a production multi-stage (build -> nginx) image is Phase 14 work.
FROM node:22-slim

WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install

COPY . .

EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
