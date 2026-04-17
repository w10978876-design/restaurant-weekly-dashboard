FROM node:20-bookworm-slim

WORKDIR /app

# Python runtime for dashboard payload generation
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Install Node dependencies first (cache-friendly)
COPY package*.json ./
RUN npm ci

# Install Python dependencies
COPY requirements.txt ./
RUN pip3 install --no-cache-dir -r requirements.txt

# Copy source
COPY . .

# Build frontend assets
RUN npm run build

ENV NODE_ENV=production
ENV PORT=3010

EXPOSE 3010

CMD ["npm", "run", "start"]
