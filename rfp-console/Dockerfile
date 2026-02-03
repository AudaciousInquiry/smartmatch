FROM node:20-alpine

WORKDIR /app

RUN npm install -g npm@latest

# Copy package files
COPY package*.json ./

# Remove any cached lockfile and install fresh with exact versions
RUN rm -f package-lock.json && npm install --legacy-peer-deps

# Manually download and install patched versions of next, glob, and tar
RUN apk add --no-cache curl && \
    rm -rf node_modules/next node_modules/glob node_modules/tar && \
    cd /tmp && \
    curl -sL https://registry.npmjs.org/next/-/next-15.4.11.tgz -o next.tgz && \
    curl -sL https://registry.npmjs.org/glob/-/glob-11.1.0.tgz -o glob.tgz && \
    curl -sL https://registry.npmjs.org/tar/-/tar-7.5.7.tgz -o tar.tgz && \
    cd /app/node_modules && \
    tar -xzf /tmp/next.tgz && mv package next && \
    tar -xzf /tmp/glob.tgz && mv package glob && \
    tar -xzf /tmp/tar.tgz && mv package tar && \
    rm -f /tmp/*.tgz && \
    rm -rf /usr/local/lib/node_modules/npm/node_modules/tar && \
    cp -r tar /usr/local/lib/node_modules/npm/node_modules/

# Copy the rest of the application
COPY . .

# Expose the Next.js default port
EXPOSE 3000

# Run in development mode by default
CMD ["npm", "run", "dev"]

# For production, use:
# RUN npm run build
# CMD ["npm", "start"]
