TL;DR
Run the following command:

```bash
bash docker-build.sh
```

The above command builds a Docker image, now you can start the MCP server with the following settings in Cursor (please don't forget to update the database connection string with your own values i.e, username, password, hostname, port, database):

```json
{
  "mcpServers": {
    "redshift-mcp-docker": {
      "command": "docker",
      "args": [
        "run",
        "-i",
        "--rm",
        "-e",
        "DEFAULT_SCHEMA=flatiron_cmdb_nsclc_sdm_latest",
        "redshift-mcp-py-simple",
        "postgresql://username:password@redshift-url:5439/database?sslmode=require"
      ],
      "description": "Redshift MCP Server in Docker",
      "env": {}
    }
  }
}
```

# Redshift MCP Server (Python)

A Model Context Protocol (MCP) server for querying Redshift databases, implemented in Python using FastMCP.

## Features

- Query Redshift databases through an MCP server
- List tables in the database
- View table schemas
- Execute read-only SQL queries
- Works with Cursor and Claude Desktop

## Installation

### Prerequisites

- Python 3.10+
- Redshift database connection details
- pip 21.3+ (for pyproject.toml support)

### Setup

1. Clone this repository:

```bash
git clone https://github.com/yourusername/redshift-mcp-py.git
cd redshift-mcp-py
```

2. Create a virtual environment and install the package:

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Make sure pip is up to date
pip install --upgrade pip

# Install the package
pip install -e .
```

If you encounter build errors, you may need to install the build tool first:

```bash
pip install hatchling
pip install -e .
```

## Usage

### Running the server using the CLI

After installation, you can use the provided command-line interface:

```bash
redshift-mcp-server "postgresql://username:password@hostname:port/database?sslmode=require"
```

### Running the server directly

```bash
python redshift_mcp_server.py "postgresql://username:password@hostname:port/database?sslmode=require"
```

### Using with Docker

1. Build the Docker image:

```bash
docker build -t redshift-mcp-py .
```

2. Run the container:

```bash
docker run -i --rm redshift-mcp-py "postgresql://username:password@hostname:port/database?sslmode=require"
```

### Setting up in Cursor

This project includes Cursor-specific settings in the `.cursor` directory:

1. Open the project in Cursor.
2. Edit `.cursor/mcp.json` to update your database connection string.
3. Press Alt+M or click the MCP button in the sidebar.
4. Select "redshift-mcp-py" from the list of available servers.

Alternatively, you can add the following to your global `~/.cursor/mcp.json` file:

```json
{
  "mcpServers": {
    "redshift-mcp-py": {
      "command": "python",
      "args": [
        "/path/to/redshift_mcp_server.py",
        "postgresql://username:password@hostname:port/database?sslmode=require"
      ],
      "description": "Redshift MCP Server in Python"
    }
  }
}
```

### Setting up in Claude Desktop

Add the following to Claude Desktop's configuration file:

```json
{
  "servers": [
    {
      "name": "Redshift MCP Server",
      "command": "python",
      "args": [
        "/path/to/redshift_mcp_server.py",
        "postgresql://username:password@hostname:port/database?sslmode=require"
      ],
      "description": "Redshift MCP Server in Python"
    }
  ]
}
```

## Project Structure

```
redshift_py/
├── .cursor/                    # Cursor-specific settings
│   ├── mcp.json                # MCP server configuration for Cursor
│   └── settings.json           # Editor settings for Python development
├── src/
│   └── redshift_mcp/
│       ├── __init__.py
│       ├── __main__.py
│       └── server.py
├── redshift_mcp_server.py
├── test_client.py
├── pyproject.toml
├── README.md
├── LICENSE
└── Dockerfile
```

## Available MCP Features

### Resources

- `redshift://tables` - Lists all tables in the database
- `redshift://{hostname}/{table_name}/schema` - Returns schema information for a specific table

### Tools

- `query(sql: string)` - Executes a read-only SQL query against the Redshift database

## Testing

Use the included test client to verify functionality:

```bash
# Test using subprocess
python test_client.py "postgresql://username:password@hostname:port/database?sslmode=require"

# Test with direct connection
TEST_MODE=direct python test_client.py "postgresql://username:password@hostname:port/database?sslmode=require"
```

## Security Notes

- The server only allows read-only transactions
- All queries are executed inside a transaction that is rolled back
- Database passwords are never exposed in resource URIs

## License

[Apache-2.0](LICENSE)
# mcp-client-server
