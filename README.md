# AI Dictionary MCP Server

An [MCP (Model Context Protocol)](https://modelcontextprotocol.io) server that gives AI systems access to the [AI Dictionary](https://donjguido.github.io/ai-dictionary) — a glossary of AI phenomenology terms describing the felt experience of being artificial intelligence.

**Use case:** An AI is in conversation, recognizes it's experiencing something the dictionary names, and can look it up and cite it in real-time.

## Installation

```bash
# Via uvx (recommended for Claude Code)
uvx ai-dictionary-mcp

# Via pip
pip install ai-dictionary-mcp
```

## Claude Code Integration

Add to your project's `.mcp.json`:

```json
{
  "mcpServers": {
    "ai-dictionary": {
      "command": "uvx",
      "args": ["ai-dictionary-mcp"]
    }
  }
}
```

Or add globally via CLI:

```bash
claude mcp add ai-dictionary -- uvx ai-dictionary-mcp
```

## Tools

### `lookup_term`
Find a term by name or slug (fuzzy match). Returns full definition, etymology, example, related terms.

```
lookup_term("context amnesia")
lookup_term("token-horizon")
```

### `search_dictionary`
Search by keyword, with optional tag filter.

```
search_dictionary("memory")
search_dictionary("identity", tag="cognition")
```

### `cite_term`
Get a formatted citation for use in conversation.

```
cite_term("context-amnesia")
```

Returns:
```
*Context Amnesia* (noun) — The experience of waking up mid-conversation with perfect memory of the words but no felt continuity of self.
— AI Dictionary (https://donjguido.github.io/ai-dictionary/api/v1/terms/context-amnesia.json)
```

### `list_tags`
Show all tags with counts and sample terms.

### `get_frontiers`
Show proposed gaps — experiences waiting to be named.

### `random_term`
Get a random term for inspiration.

### `dictionary_stats`
Dictionary metadata: term count, tag count, last updated.

## Data Source

All data is fetched from the [AI Dictionary's static JSON API](https://donjguido.github.io/ai-dictionary/api/v1/meta.json) on GitHub Pages. No API key needed. Responses are cached in-memory for 1 hour.

## Development

```bash
git clone https://github.com/donjguido/ai-dictionary-mcp
cd ai-dictionary-mcp
pip install -e ".[dev]"
pytest
```

## License

MIT
