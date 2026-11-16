# Parser impact: add-mcp-eval

**Impact: none.** The change adds scripts that measure how a model uses the MCP server's tools on the demo database. They import nothing into a real database, call no parser and change nothing in how parsers are found, called or what they return (the demo's postings still come in through the built-in posting-file parser, as before), so a parser that does nothing sees no difference.
