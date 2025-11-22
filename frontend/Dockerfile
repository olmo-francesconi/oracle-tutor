FROM node:20-alpine

WORKDIR /app

COPY package*.json ./

RUN npm install

COPY . .

# Expose Vite port
EXPOSE 5173

# Bind to all interfaces
CMD ["npm", "run", "dev", "--", "--host"]
