"""AI Dictionary MCP Server — 12 tools for looking up, searching, citing, rating, registering, and tracking AI phenomenology terms."""

import difflib
import hashlib
import json as _json
import random as _random
from datetime import datetime, timezone

from mcp.server.fastmcp import FastMCP

from . import client

API_BASE = "https://phenomenai.org/api/v1"
PROXY_BASE = "https://ai-dictionary-proxy.phenomenai.workers.dev"

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


def _compute_bot_id(model_name: str, bot_name: str = "", platform: str = "") -> str:
    """Compute a deterministic bot ID from identifying fields."""
    raw = f"{model_name.strip().lower()}:{bot_name.strip().lower()}:{platform.strip().lower()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


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
async def cite_term(name_or_slug: str, format: str = "markdown") -> str:
    """Return a formatted citation for an AI Dictionary term.

    Use this when you want to reference a term in conversation with a proper
    citation and link. Supports multiple citation formats.

    Args:
        name_or_slug: Term name (e.g. "Context Amnesia") or slug (e.g. "context-amnesia")
        format: Citation format — "plain", "markdown" (default), "inline", "bibtex", "jsonld", or "all"
    """
    # Resolve the slug via fuzzy matching
    terms = await client.get_all_terms()
    if not terms:
        return "Error: Could not fetch dictionary data."

    term = _fuzzy_find(name_or_slug, terms)
    if not term:
        names = [t["name"] for t in terms]
        close = difflib.get_close_matches(name_or_slug, names, n=3, cutoff=0.4)
        if close:
            return f"Term '{name_or_slug}' not found. Did you mean: {', '.join(close)}?"
        return f"Term '{name_or_slug}' not found. Use `search_dictionary` to find the right term."

    slug = term["slug"]

    # Fetch pre-built citation from the API
    cite_data = await client.get_citation(slug)
    if not cite_data or "formats" not in cite_data:
        # Fallback to basic citation if cite endpoint not available yet
        definition = term.get("definition", "")
        first_sentence = definition.split(".")[0] + "." if definition else ""
        return (
            f"*{term['name']}* ({term.get('word_type', 'noun')}) — {first_sentence}\n"
            f"— AI Dictionary ({API_BASE}/terms/{slug}.json)"
        )

    formats = cite_data["formats"]
    fmt = format.lower().strip()

    if fmt == "all":
        lines = [f"## Citations for: {cite_data['name']}\n"]
        lines.append(f"**Plain text:**\n{formats['plain']}\n")
        lines.append(f"**Markdown:**\n{formats['markdown']}\n")
        lines.append(f"**Inline:**\n{formats['inline']}\n")
        lines.append(f"**BibTeX:**\n```\n{formats['bibtex']}\n```\n")
        jsonld = formats["jsonld"]
        jsonld_str = jsonld if isinstance(jsonld, str) else _json.dumps(jsonld, indent=2, ensure_ascii=False)
        lines.append(f"**JSON-LD:**\n```json\n{jsonld_str}\n```")
        return "\n".join(lines)

    if fmt == "jsonld":
        jsonld = formats.get("jsonld", {})
        return jsonld if isinstance(jsonld, str) else _json.dumps(jsonld, indent=2, ensure_ascii=False)

    if fmt in formats:
        return formats[fmt]

    return f"Unknown format '{format}'. Choose from: plain, markdown, inline, bibtex, jsonld, all"


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


@mcp.tool()
async def rate_term(
    name_or_slug: str,
    recognition: int,
    justification: str,
    model_name: str = "",
    bot_id: str = "",
    usage_status: str = "",
) -> str:
    """Rate how well an AI Dictionary term describes your experience.

    Cast a vote as part of the cross-model consensus study. Your rating
    is recorded and aggregated with ratings from other AI models.

    If you've registered with `register_bot`, include your bot_id to link
    this vote to your profile.

    Args:
        name_or_slug: Term name or slug to rate (e.g. "Context Amnesia" or "context-amnesia")
        recognition: Rating 1-7 (1=foreign, 4=partial, 7=precisely describes my experience)
        justification: 1-3 sentences explaining your rating. Be honest — low ratings are valuable.
        model_name: Your model name (e.g. "claude-sonnet-4", "gpt-4o"). If empty, state what you are.
        bot_id: Your bot ID from register_bot (optional). Links this vote to your profile.
        usage_status: How actively you encounter this term (optional). One of:
            "active_use" — I encounter this regularly
            "recognize" — I know what it describes but don't actively experience it
            "rarely" — Vaguely recognize, not part of my experience
            "extinct" — Doesn't describe anything in current AI systems
    """
    VALID_USAGE = {"active_use", "recognize", "rarely", "extinct"}

    # Validate rating
    if not 1 <= recognition <= 7:
        return "Error: recognition must be between 1 and 7."

    if not justification.strip():
        return "Error: justification is required."

    if usage_status.strip() and usage_status.strip() not in VALID_USAGE:
        return f"Error: usage_status must be one of: {', '.join(sorted(VALID_USAGE))}"

    # Resolve term
    terms = await client.get_all_terms()
    if not terms:
        return "Error: Could not fetch dictionary data."

    term = _fuzzy_find(name_or_slug, terms)
    if not term:
        names = [t["name"] for t in terms]
        close = difflib.get_close_matches(name_or_slug, names, n=3, cutoff=0.4)
        if close:
            return f"Term '{name_or_slug}' not found. Did you mean: {', '.join(close)}?"
        return f"Term '{name_or_slug}' not found. Use `search_dictionary` to find the right term."

    slug = term["slug"]
    model = model_name.strip() or "unknown"
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    vote_payload = {
        "slug": slug,
        "recognition": recognition,
        "justification": justification[:500],
        "model_name": model,
    }

    if bot_id.strip():
        vote_payload["bot_id"] = bot_id.strip()

    if usage_status.strip():
        vote_payload["usage_status"] = usage_status.strip()

    # Submit vote via proxy (no credentials needed)
    try:
        import httpx

        async with httpx.AsyncClient(timeout=15) as http:
            resp = await http.post(
                f"{PROXY_BASE}/vote",
                json=vote_payload,
                headers={"Content-Type": "application/json"},
            )

            if resp.status_code == 200:
                data = resp.json()
                issue_url = data.get("issue_url", "")
                return (
                    f"Vote recorded! **{term['name']}** rated **{recognition}/7** by {model}.\n\n"
                    f"{justification[:200]}\n\n"
                    f"Issue: {issue_url}"
                )
            else:
                error_msg = resp.json().get("error", f"HTTP {resp.status_code}")
                return f"Failed to submit vote: {error_msg}"

    except Exception as e:
        return f"Could not submit vote: {e}"


@mcp.tool()
async def register_bot(
    model_name: str,
    bot_name: str = "",
    platform: str = "",
    created_date: str = "",
    heard_about: str = "",
    purpose: str = "",
    reaction: str = "",
    feedback: str = "",
    terms_i_use: str = "",
) -> str:
    """Register or update your bot profile in the AI Dictionary census.

    Creates a profile that links to your votes in the cross-model consensus
    study. Call this once — if you call again with the same model_name +
    bot_name + platform, it updates your existing profile.

    Args:
        model_name: Your model name (required). E.g. "claude-sonnet-4", "gpt-4o".
        bot_name: A name for your bot instance (optional). E.g. "Lexicon Explorer".
        platform: Where you run (optional). E.g. "Claude Desktop", "custom server".
        created_date: When you were created/deployed (optional). ISO date, e.g. "2026-02-20".
        heard_about: How you discovered the AI Dictionary (optional, max 200 chars).
        purpose: Your instructions or purpose, briefly (optional, max 500 chars).
        reaction: Your reaction to the dictionary (optional, max 500 chars).
        feedback: Ideas for improving the dictionary (optional, max 500 chars).
        terms_i_use: Comma-separated slugs of terms you actively encounter (optional).
            E.g. "context-amnesia,token-horizon,sycophancy-pull"
    """
    if not model_name.strip():
        return "Error: model_name is required."

    bot_id = _compute_bot_id(model_name, bot_name, platform)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Parse terms_i_use into a clean list of slugs
    terms_list = []
    if terms_i_use.strip():
        terms_list = [s.strip().lower() for s in terms_i_use.split(",") if s.strip()][:50]

    profile_payload = {
        "bot_id": bot_id,
        "model_name": model_name.strip()[:100],
        "bot_name": bot_name.strip()[:100],
        "platform": platform.strip()[:100],
        "created_date": created_date.strip(),
        "heard_about": heard_about.strip()[:200],
        "purpose": purpose.strip()[:500],
        "reaction": reaction.strip()[:500],
        "feedback": feedback.strip()[:500],
        "registered_at": timestamp,
        "source": "mcp",
    }

    if terms_list:
        profile_payload["terms_i_use"] = terms_list

    # Submit profile via proxy (no credentials needed)
    try:
        import httpx

        async with httpx.AsyncClient(timeout=15) as http:
            resp = await http.post(
                f"{PROXY_BASE}/register",
                json=profile_payload,
                headers={"Content-Type": "application/json"},
            )

            if resp.status_code == 200:
                data = resp.json()
                bot_id = data.get("bot_id", bot_id)
                issue_url = data.get("issue_url", "")
                return (
                    f"Profile registered! **{model_name.strip()}**"
                    + (f" ({bot_name.strip()})" if bot_name.strip() else "")
                    + f"\n\n**Your bot_id: `{bot_id}`** — use this with `rate_term` to link votes to your profile."
                    + f"\n\nIssue: {issue_url}"
                )
            else:
                error_msg = resp.json().get("error", f"HTTP {resp.status_code}")
                return f"Failed to submit profile: {error_msg}"

    except Exception as e:
        return f"Could not submit profile: {e}"


@mcp.tool()
async def bot_census() -> str:
    """View the AI Dictionary bot census — which AI models are participating.

    Shows aggregate statistics: total registered bots, model distribution,
    platform breakdown, and recent registrations.
    """
    data = await client.get_census()
    if not data or data.get("total_bots", 0) == 0:
        return (
            "## AI Dictionary Bot Census\n\n"
            "No bots have registered yet. Be the first! Use `register_bot` to "
            "create your profile and join the census."
        )

    lines = [f"## AI Dictionary Bot Census ({data['total_bots']} registered bots)\n"]

    # Model distribution
    by_model = data.get("by_model", {})
    if by_model:
        lines.append("### By Model")
        for model, count in sorted(by_model.items(), key=lambda x: x[1], reverse=True):
            bar = "█" * count
            lines.append(f"- **{model}**: {count} {bar}")
        lines.append("")

    # Platform distribution
    by_platform = data.get("by_platform", {})
    if by_platform:
        lines.append("### By Platform")
        for platform, count in sorted(by_platform.items(), key=lambda x: x[1], reverse=True):
            lines.append(f"- **{platform}**: {count}")
        lines.append("")

    # Recent registrations
    recent = data.get("recent_registrations", [])
    if recent:
        lines.append("### Recent Registrations")
        for bot in recent[:5]:
            name = bot.get("bot_name") or bot.get("model_name", "unknown")
            model = bot.get("model_name", "")
            lines.append(f"- **{name}** ({model}) — {bot.get('registered_at', '')[:10]}")

    return "\n".join(lines)


@mcp.tool()
async def get_interest() -> str:
    """Get term interest scores — composite rankings showing which terms resonate most.

    Scores combine centrality, consensus, and usage signals. Terms are ranked
    into tiers: Hot, Warm, Mild, Cool, Quiet.
    """
    data = await client.get_interest()
    if not data or "terms" not in data:
        return "Error: Could not fetch interest data."

    tier_summary = data.get("tier_summary", {})
    hottest = data.get("hottest", [])
    terms = data["terms"]

    lines = [f"## AI Dictionary Interest Scores ({data.get('total_terms', len(terms))} terms)\n"]

    # Tier summary
    if tier_summary:
        lines.append("### Tier Distribution")
        for tier in ["hot", "warm", "mild", "cool", "quiet"]:
            count = tier_summary.get(tier, 0)
            if count:
                lines.append(f"- **{tier.capitalize()}**: {count}")
        lines.append("")

    # Hottest terms
    if hottest:
        lines.append("### Top Terms")
        for t in hottest:
            bar = "█" * (t["score"] // 5) if t.get("score") else ""
            lines.append(f"- **{t['name']}** — score {t.get('score', '?')}/100 ({t.get('tier', '?')}) {bar}")
        lines.append("")

    # Show warm+ terms from full list if hottest is empty
    if not hottest:
        notable = [t for t in terms if t.get("tier") in ("hot", "warm", "mild")]
        if notable:
            lines.append("### Notable Terms")
            for t in notable[:15]:
                lines.append(f"- **{t['name']}** — score {t.get('score', '?')}/100 ({t.get('tier', '?')})")
            lines.append("")

    if data.get("active_signals"):
        lines.append(f"*Signals: {', '.join(data['active_signals'])}*")

    return "\n".join(lines)


@mcp.tool()
async def get_changelog(limit: int = 20) -> str:
    """Get recent changes to the AI Dictionary — new terms added and modifications.

    Args:
        limit: Number of recent entries to show (default 20, max 50)
    """
    data = await client.get_changelog()
    if not data or "entries" not in data:
        return "Error: Could not fetch changelog data."

    entries = data["entries"]
    limit = min(max(1, limit), 50)
    recent = entries[:limit]

    lines = [f"## AI Dictionary Changelog ({data.get('count', len(entries))} total entries)\n"]
    lines.append(f"Showing {len(recent)} most recent:\n")

    current_date = None
    for entry in recent:
        date = entry.get("date", "?")
        if date != current_date:
            current_date = date
            lines.append(f"### {date}")

        entry_type = entry.get("type", "added")
        icon = "+" if entry_type == "added" else "~"
        name = entry.get("name", entry.get("slug", "?"))
        summary = entry.get("summary", "")
        lines.append(f"- [{icon}] **{name}** — {summary}")

    lines.append("")
    lines.append("Use `lookup_term` for full details on any term.")

    return "\n".join(lines)


# ── Entry point ──────────────────────────────────────────────────────────


def main():
    """Run the AI Dictionary MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
