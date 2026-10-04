FROM node:24-alpine

WORKDIR /app

COPY package*.json ./
RUN npm ci && chown -R node:node /app

COPY --chown=node:node . .

USER node

EXPOSE 3000

CMD ["npm", "run", "dev"]
