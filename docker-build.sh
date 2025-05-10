#!/bin/bash
set -e

# Move to the directory containing this script
cd "$(dirname "$0")"

echo "Building simple Docker image for Redshift MCP Server..."
docker build -t redshift-mcp-py-simple -f Dockerfile .

echo "Image built successfully!"
echo "To run the MCP server with Docker:"
echo "docker run -i --rm -e DATABASE_URL=\"postgresql://username:password@hostname:port/database?sslmode=require\" redshift-mcp-py-simple" 
