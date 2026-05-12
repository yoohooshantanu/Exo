FROM node:20-alpine

WORKDIR /app

RUN npm install -g vite

COPY package.json ./
RUN npm install

COPY . .

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host"]
