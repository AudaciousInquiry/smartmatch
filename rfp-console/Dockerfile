FROM node:20-alpine

WORKDIR /app

# Copy package files
COPY package*.json ./

# Install dependencies
RUN npm install

# Copy the rest of the application
COPY . .

# Expose the Next.js default port
EXPOSE 3000

# Run in development mode by default
CMD ["npm", "run", "dev"]

# For production, use:
# RUN npm run build
# CMD ["npm", "start"]
