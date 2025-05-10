import sys
import os
from urllib.parse import urlparse, urlunparse, parse_qs
import psycopg2
from psycopg2.extras import RealDictCursor
from fastmcp import FastMCP, Context
from dotenv import load_dotenv

def create_server(database_url=None, schema_name=None):
    mcp = FastMCP("Redshift MCP Server")
    load_dotenv()

    if not database_url:
        if len(sys.argv) > 1:
            database_url = sys.argv[1]
        else:
            database_url = os.environ.get("DATABASE_URL")

    if not database_url:
        print("Error: No database URL provided via parameter, env or CLI", file=sys.stderr)
        sys.exit(1)

    if not schema_name and len(sys.argv) > 2:
        schema_name = sys.argv[2]
    else:
        schema_name = os.environ.get("DEFAULT_SCHEMA", "flatiron_cmdb_nsclc_sdm_latest")

    parsed_url = urlparse(database_url)
    netloc_parts = parsed_url.netloc.split('@')
    resource_netloc = netloc_parts[1] if len(netloc_parts) > 1 else parsed_url.netloc

    print(f"Using schema: {schema_name}", file=sys.stderr)

    try:
        conn = psycopg2.connect(database_url)
        with conn.cursor() as cursor:
            cursor.execute(f"SET search_path TO {schema_name}")
            cursor.execute("SELECT current_schema()")
            current_schema = cursor.fetchone()[0]
            print(f"Connected. Current schema: {current_schema}", file=sys.stderr)

            if current_schema != schema_name:
                print(f"Warning: Schema is {current_schema}, attempting to set to {schema_name}", file=sys.stderr)
                cursor.execute(f"SET search_path = {schema_name}")
                cursor.execute("SELECT current_schema()")
                current_schema = cursor.fetchone()[0]
                print(f"Updated schema to: {current_schema}", file=sys.stderr)
    except Exception as e:
        print(f"Database connection failed: {e}", file=sys.stderr)
        sys.exit(1)

    @mcp.resource("redshift://schema")
    async def list_schema() -> dict:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(f"SET search_path TO {schema_name}")
            cursor.execute(
                """
                SELECT table_name, column_name, data_type, ordinal_position 
                FROM information_schema.columns 
                WHERE table_schema = %s 
                ORDER BY table_name, ordinal_position
                """,
                (schema_name,)
            )
            columns = cursor.fetchall()

        return {
            "schema": schema_name,
            "columns": [dict(row) for row in columns]
        }

    @mcp.resource("redshift://tables")
    async def list_tables() -> dict:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(f"SET search_path TO {schema_name}")
            cursor.execute(
                """
                SELECT table_name
                FROM information_schema.tables 
                WHERE table_schema = %s 
                ORDER BY table_name
                """,
                (schema_name,)
            )
            tables = cursor.fetchall()

        resources = []
        for table in tables:
            uri = f"redshift://{resource_netloc}/{table['table_name']}/schema"
            resources.append({
                "uri": uri,
                "mimeType": "application/json",
                "name": f"{table['table_name']} table schema"
            })

        return {"resources": resources}

    @mcp.tool()
    async def get_table_schema(table_name: str, ctx: Context = None) -> dict:
        if ctx:
            await ctx.info(f"Fetching schema for: {table_name}")

        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(f"SET search_path TO {schema_name}")
            cursor.execute(
                """
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_name = %s AND table_schema = %s
                """,
                (table_name, schema_name)
            )
            columns = cursor.fetchall()
            return {"columns": columns}

    @mcp.tool()
    async def query(sql: str, ctx: Context = None) -> dict:
        if ctx:
            await ctx.info(f"Running query: {sql}")

        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            try:
                cursor.execute(f"SET search_path TO {schema_name}")
                cursor.execute("BEGIN TRANSACTION READ ONLY")
                cursor.execute(sql)
                results = cursor.fetchall()
                return [dict(row) for row in results]
            except Exception as e:
                if ctx:
                    await ctx.error(f"Query failed: {e}")
                raise
            finally:
                cursor.execute("ROLLBACK")

    @mcp.tool()
    async def resolve_resource(uri: str) -> dict:
        parsed = urlparse(uri)
        path_parts = parsed.path.strip("/").split("/")

        if parsed.netloc == "tables":
            return await list_tables()

        if len(path_parts) != 2 or path_parts[1] != "schema":
            raise ValueError("Invalid schema URI")

        table_name = path_parts[0]
        return await get_table_schema(table_name)

    return mcp


def main():
    try:
        mcp = create_server()
        print("Starting MCP server on http://localhost:8000", file=sys.stderr)
        print("SSE endpoint available at http://localhost:8000/sse", file=sys.stderr)
        mcp.run(
            transport="sse",
            host="localhost",
            port=8000
        )
    except Exception as e:
        print(f"Error starting MCP server: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
