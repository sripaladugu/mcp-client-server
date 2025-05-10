FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY . .

# Install dependencies explicitly
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir "fastmcp>=2.0.0" "psycopg2-binary>=2.9.9" "pydantic>=2.0.0" && \
    pip install --no-cache-dir -e .

# Environment variables
ENV PYTHONUNBUFFERED=1

# Add a simple wrapper script to print info and run the server
RUN echo '#!/bin/bash' > /app/docker-wrapper.sh && \
    echo 'echo "Starting Redshift MCP Server..." >&2' >> /app/docker-wrapper.sh && \
    echo 'echo "Python version: $(python --version)" >&2' >> /app/docker-wrapper.sh && \
    echo 'echo "Working directory: $(pwd)" >&2' >> /app/docker-wrapper.sh && \
    echo 'echo "Command line args: $@" >&2' >> /app/docker-wrapper.sh && \
    echo 'python -u redshift_mcp_server.py "$@"' >> /app/docker-wrapper.sh && \
    chmod +x /app/docker-wrapper.sh

# Set the entrypoint
ENTRYPOINT ["/app/docker-wrapper.sh"] 