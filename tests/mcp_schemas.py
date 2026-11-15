"""Checking MCP tool results against the output schemas the server advertises (needs the `mcp` extra; jsonschema comes
with it). The schemas are closed first, so a field a tool returns but its schema doesn't name fails too."""

import json

import anyio
import jsonschema
from mcp import Client

from jobhunt import mcp_server, mcp_tools


def closed(schema):
    """`schema` with every object that lists its properties closed to any others (an explicit
    `additionalProperties`, such as a posting's free-form `details`, is kept)."""
    if isinstance(schema, dict):
        out = {key: closed(value) for key, value in schema.items()}
        if "properties" in out and "additionalProperties" not in out:
            out["additionalProperties"] = False
        return out
    if isinstance(schema, list):
        return [closed(value) for value in schema]
    return schema


def output_schemas(engine) -> dict:
    """Each tool's output schema as a client lists it, closed, as a validator."""

    async def listed():
        async with Client(mcp_server.build(engine, tuple(mcp_tools.SCOPES))) as client:
            return (await client.list_tools()).tools

    return {
        tool.name: jsonschema.Draft202012Validator(closed(tool.output_schema))
        for tool in anyio.run(listed)
    }


def check(validators, name, result):
    """Fail with every schema error of `result` (as it travels: through JSON) for tool `name`."""
    errors = [f"{'/'.join(map(str, e.absolute_path)) or '(top)'}: {e.message}"
              for e in validators[name].iter_errors(json.loads(json.dumps(result)))]
    assert not errors, f"{name}: " + "; ".join(errors)
