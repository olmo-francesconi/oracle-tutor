# Use an official Node runtime as a parent image
FROM node:18-alpine

# Set the working directory in the container
WORKDIR /app

# Copy package.json and package-lock.json
COPY package*.json ./

# Install dependencies
RUN npm install

# Copy the rest of the application code
COPY server.js .
COPY public/ public/

# Make port 3000 available to the world outside this container
EXPOSE 3000

# Define environment variable for API URL (can be overridden)
ENV API_URL=http://api:8000

# Run the application
CMD ["node", "server.js"]
