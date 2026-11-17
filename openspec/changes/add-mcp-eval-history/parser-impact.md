# Parser impact: add-mcp-eval-history

**Impact: none.** The change only alters the scripts that measure how a model uses the MCP server on the demo database (the history each question is asked with, the order of the questions, comparisons and docs). They import nothing into a real database, call no parser and change nothing in how parsers are found, called or what they return, so a parser that does nothing sees no difference.
