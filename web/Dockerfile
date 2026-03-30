FROM node:20-alpine AS builder

WORKDIR /app

COPY package*.json ./
COPY bun.lock ./

RUN npm install -g bun && bun install

COPY . .
RUN VITE_API_URL= bun run build

FROM nginx:alpine

COPY --from=builder /app/dist /usr/share/nginx/html

COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
