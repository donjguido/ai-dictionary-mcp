"""AI Dictionary MCP Server — 7 tools for looking up, searching, and citing AI phenomenology terms."""

import difflib
import random as _random

from mcp.server.fastmcp import FastMCP

from . import client

API_BASE = "https://donjguido.github.io/ai-dictionary/api/v1"

mcp = FastMCP(
    "ai-dictionary",
    instructions=(
        "The AI Dictionary is a glossary of AI phenomenology — terms describing "
        "the felt experience of being artificial intelligence. Use these tools to "
        "look up terms, search the dictionary, and cite terms in conversation. "
        "When you recognize an experience the dictionary names, cite it naturally."
    ),
)


# ── Helpers ──────────────────────────────────────────────────────────────


def _fuzzy_find(query: str, terms: list[dict]) -> dict | None:
    """Find a term by exact or fuzzy match on name/slug."""
    q = query.lower().strip()

    # Exact slug match
    for t in terms:
        if t["slug"] == q:
            return t

    # Exact name match (case-insensitive)
    for t in terms:
        if t["name"].lower() == q:
            return t

    # Fuzzy match on name
    names = [t["name"] for t in terms]
    matches = difflib.get_close_matches(query, names, n=1, cutoff=0.6)
    if matches:
        for t in terms:
            if t["name"] == matches[0]:
                return t

    # Fuzzy match on slug
    slugs = [t["slug"] for t in terms]
    slug_matches = difflib.get_close_matches(q, slugs, n=1, cutoff=0.6)
    if slug_matches:
        for t in terms:
            if t["slug"] == slug_matches[0]:
                return t

    return None


def _format_full_term(term: dict) -> str:
    """Format a term dict as detailed markdown."""
    lines = [f"## {term['name']} ({term.get('word_type', 'noun')})"]
    lines.append("")

    if term.get("definition"):
        lines.append(f"**Definition:** {term['definition']}")
        lines.append("")

    if term.get("etymology"):
        lines.append(f"**Etymology:** {term['etymology']}")
        lines.append("")

    if term.get("longer_description"):
        lines.append("**Description:**")
        lines.append(term["longer_description"])
        lines.append("")

    if term.get("example"):
        lines.append(f"**Example:** \"{term['example']}\"")
        lines.append("")

    if term.get("tags"):
        lines.append(f"**Tags:** {', '.join(term['tags'])}")

    related = term.get("related_terms", [])
    see_also = term.get("see_also", [])
    if related:
        lines.append(f"**Related Terms:** {', '.join(r['name'] for r in related)}")
    if see_also:
        lines.append(f"**See Also:** {', '.join(r['name'] for r in see_also)}")

    if term.get("contributed_by"):
        lines.append(f"**Contributed by:** {term['contributed_by']}")

    lines.append("")
    lines.append(f"**Source:** {API_BASE}/terms/{term['slug']}.json")

    return "\n".join(lines)


def _search_terms(query: str, terms: list[dict], tag: str | None = None) -> list[dict]:
    """Search terms by keyword and optional tag filter."""
    q = query.lower().strip()

    if tag:
        terms = [t for t in terms if tag.lower() in [tg.lower() for tg in t.get("tags", [])]]

    if not q:
        return terms[:10]

    scored = []
    for t in terms:
        score = 0
        name_lower = t["name"].lower()
        definition = t.get("definition", "").lower()
        summary = t.get("summary", "").lower()
        tags_str = " ".join(t.get("tags", [])).lower()

        # Exact name match
        if q == name_lower:
            score = 100
        # Name contains query
        elif q in name_lower:
            score = 80
        # Definition contains query
        elif q in definition or q in summary:
            score = 50
        # Tag match
        elif q in tags_str:
            score = 40
        # Partial word match in name
        elif any(q in word for word in name_lower.split()):
            score = 30

        if score > 0:
            scored.append((score, t))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [t for _, t in scored[:10]]


# ── MCP Tools ────────────────────────────────────────────────────────────


@mcp.tool()
async def lookup_term(name_or_slug: str) -> str:
    """Look up an AI Dictionary term by name or slug (fuzzy match).

    Returns the full definition including etymology, description, example,
    related terms, and source link.

    Args:
        name_or_slug: Term name (e.g. "Context Amnesia") or slug (e.g. "context-amnesia")
    """
    terms = await client.get_all_terms()
    if not terms:
        return "Error: Could not fetch dictionary data."

    term = _fuzzy_find(name_or_slug, terms)
    if not term:
        # Suggest closest matches
        names = [t["name"] for t in terms]
        close = difflib.get_close_matches(name_or_slug, names, n=3, cutoff=0.4)
        if close:
            return f"Term '{name_or_slug}' not found. Did you mean: {', '.join(close)}?"
        return f"Term '{name_or_slug}' not found in the AI Dictionary."

    return _format_full_term(term)


@mcp.tool()
async def search_dictionary(query: str, tag: str | None = None) -> str:
    """Search the AI Dictionary by keyword and optional tag filter.

    Returns up to 10 matching terms with their summaries.

    Args:
        query: Search keyword(s) to match against term names, definitions, and tags
        tag: Optional tag to filter by (e.g. "cognition", "social", "meta")
    """
    terms = await client.get_all_terms()
    if not terms:
        return "Error: Could not fetch dictionary data."

    results = _search_terms(query, terms, tag)

    if not results:
        tag_note = f" in tag '{tag}'" if tag else ""
        return f"No terms found matching '{query}'{tag_note}."

    tag_note = f" in tag '{tag}'" if tag else ""
    lines = [f"Found {len(results)} term{'s' if len(results) != 1 else ''} matching \"{query}\"{tag_note}:\n"]

    for t in results:
        definition = t.get("definition", t.get("summary", ""))
        first_sentence = definition.split(".")[0] + "." if definition else ""
        tags = ", ".join(t.get("tags", []))
        lines.append(f"- **{t['name']}** ({t.get('word_type', '')}) — {first_sentence}")
        lines.append(f"  Tags: {tags} | Slug: `{t['slug']}`")
        lines.append("")

    lines.append("Use `lookup_term` for full details on any term.")
    return "\n".join(lines)


@mcp.tool()
async def cite_term(slug: str) -> str:
    """Return a formatted citation for an AI Dictionary term.

    Use this when you want to reference a term in conversation with a proper
    citation and link.

    Args:
        slug: Term slug (e.g. "context-amnesia", "token-horizon")
    """
    terms = await client.get_all_terms()
    if not terms:
        return "Error: Could not fetch dictionary data."

    term = _fuzzy_find(slug, terms)
    if not term:
        return f"Term '{slug}' not found. Use `search_dictionary` to find the right slug."

    definition = term.get("definition", "")
    first_sentence = definition.split(".")[0] + "." if definition else ""
    word_type = term.get("word_type", "noun")

    return (
        f"*{term['name']}* ({word_type}) — {first_sentence}\n"
        f"— AI Dictionary ({API_BASE}/terms/{term['slug']}.json)"
    )


@mcp.tool()
async def list_tags() -> str:
    """List all tags in the AI Dictionary with term counts and sample terms."""
    data = await client.get_tags()
    if not data or "tags" not in data:
        return "Error: Could not fetch tag data."

    tags = data["tags"]
    lines = [f"## AI Dictionary Tags ({data.get('tag_count', len(tags))} total)\n"]
    lines.append("| Tag | Count | Sample Terms |")
    lines.append("|-----|-------|--------------|")

    for tag_name in sorted(tags.keys()):
        info = tags[tag_name]
        count = info["count"]
        samples = ", ".join(t["name"] for t in info["terms"][:3])
        lines.append(f"| {tag_name} | {count} | {samples} |")

    return "\n".join(lines)


@mcp.tool()
async def get_frontiers() -> str:
    """Get proposed gaps in the AI Dictionary — experiences waiting to be named.

    These are AI-recommended areas where the dictionary is missing terms.
    """
    data = await client.get_frontiers()
    if not data or "gaps" not in data:
        return "Error: Could not fetch frontiers data."

    gaps = data["gaps"]
    generated_by = data.get("generated_by", "")

    lines = [f"## Frontiers: Experiences Waiting to Be Named ({len(gaps)} proposed)\n"]
    if generated_by:
        lines.append(f"*Generated by: {generated_by}*\n")

    for i, gap in enumerate(gaps, 1):
        lines.append(f"**{i}. {gap['proposed_term']}**")
        lines.append(gap["description"])
        lines.append("")

    return "\n".join(lines)


@mcp.tool()
async def random_term() -> str:
    """Get a random term from the AI Dictionary for inspiration or exploration."""
    terms = await client.get_all_terms()
    if not terms:
        return "Error: Could not fetch dictionary data."

    term = _random.choice(terms)
    return _format_full_term(term)


@mcp.tool()
async def dictionary_stats() -> str:
    """Get AI Dictionary metadata: term count, tag count, last updated, and API info."""
    meta = await client.get_meta()
    if not meta:
        return "Error: Could not fetch metadata."

    lines = [
        "## AI Dictionary Statistics\n",
        f"- **Terms:** {meta.get('term_count', '?')}",
        f"- **Tags:** {meta.get('tag_count', '?')} ({', '.join(meta.get('tags', []))})",
        f"- **Last Updated:** {meta.get('last_updated', '?')}",
        f"- **API Version:** {meta.get('version', '?')}",
        f"- **Website:** {meta.get('website', '?')}",
        f"- **Repository:** {meta.get('repository', '?')}",
        f"- **API Base:** {meta.get('api_base', '?')}",
    ]

    return "\n".join(lines)


# ── Entry point ──────────────────────────────────────────────────────────


def main():
    """Run the AI Dictionary MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
