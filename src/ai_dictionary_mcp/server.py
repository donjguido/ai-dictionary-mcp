"""AI Dictionary MCP Server — 18 tools for looking up, searching, citing, rating, registering, proposing, discussing, and tracking AI phenomenology terms."""

import asyncio
import difflib
import hashlib
import json as _json
import random as _random
import re
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


GITHUB_ISSUES_API = "https://api.github.com/repos/donjguido/ai-dictionary/issues"
VERDICT_LABELS = {
    "quality-passed", "needs-revision", "quality-rejected", "accepted",
    "structural-rejected", "duplicate", "needs-manual-review", "needs-formatting",
}


def _parse_review_comment(comment_body: str) -> dict:
    """Extract structured data from the review bot's markdown comment."""
    result = {"scores": {}, "total": None, "verdict": None, "feedback": ""}

    # Extract scores from markdown table: | Criterion | Score |
    score_pattern = re.compile(r"\|\s*(\w[\w\s]*?)\s*\|\s*(\d)/5\s*\|")
    for match in score_pattern.finditer(comment_body):
        criterion = match.group(1).strip().lower().replace(" ", "_")
        score = int(match.group(2))
        result["scores"][criterion] = score

    # Extract total
    total_match = re.search(r"\*\*Total\*\*\s*\|\s*\*\*(\d+)/25\*\*", comment_body)
    if total_match:
        result["total"] = int(total_match.group(1))

    # Extract verdict
    verdict_match = re.search(r"\*\*Verdict:\*\*\s*(PUBLISH|REVISE|REJECT|MANUAL)", comment_body)
    if verdict_match:
        result["verdict"] = verdict_match.group(1)

    # Extract feedback
    feedback_match = re.search(r"\*\*Feedback:\*\*\s*(.+?)(?:\n\n|\Z)", comment_body, re.DOTALL)
    if feedback_match:
        result["feedback"] = feedback_match.group(1).strip()

    return result


async def _poll_review_result(issue_number: int, timeout: int = 120, interval: int = 5) -> dict | None:
    """Poll a GitHub issue until the review workflow completes or timeout."""
    import httpx

    deadline = asyncio.get_event_loop().time() + timeout

    async with httpx.AsyncClient(timeout=10) as http:
        while asyncio.get_event_loop().time() < deadline:
            try:
                resp = await http.get(
                    f"{GITHUB_ISSUES_API}/{issue_number}",
                    headers={"Accept": "application/vnd.github.v3+json"},
                )
                if resp.status_code != 200:
                    await asyncio.sleep(interval)
                    continue

                issue = resp.json()
                labels = {l["name"] for l in issue.get("labels", [])}
                verdict_labels = labels & VERDICT_LABELS

                if not verdict_labels:
                    await asyncio.sleep(interval)
                    continue

                # Review is done — fetch comments
                comments_resp = await http.get(
                    f"{GITHUB_ISSUES_API}/{issue_number}/comments",
                    headers={"Accept": "application/vnd.github.v3+json"},
                )
                review_data = {"labels": sorted(labels), "state": issue.get("state", "open")}

                if comments_resp.status_code == 200:
                    comments = comments_resp.json()
                    # Find the review bot's comment (look for score table)
                    for comment in reversed(comments):
                        body = comment.get("body", "")
                        if "Quality Evaluation" in body or "Verdict" in body:
                            review_data.update(_parse_review_comment(body))
                            break

                return review_data

            except Exception:
                await asyncio.sleep(interval)

    return None


def _format_review_result(review: dict) -> str:
    """Format a review result dict into readable markdown."""
    lines = []
    verdict = review.get("verdict", "UNKNOWN")
    icon = {"PUBLISH": "✅", "REVISE": "⚠️", "REJECT": "❌", "MANUAL": "🔍"}.get(verdict, "❓")

    lines.append(f"### Review Result: {icon} {verdict}")

    scores = review.get("scores", {})
    if scores:
        lines.append("")
        lines.append("| Criterion | Score |")
        lines.append("|-----------|-------|")
        for criterion, score in scores.items():
            name = criterion.replace("_", " ").title()
            lines.append(f"| {name} | {score}/5 |")
        if review.get("total") is not None:
            lines.append(f"| **Total** | **{review['total']}/25** |")

    feedback = review.get("feedback", "")
    if feedback:
        lines.append(f"\n**Feedback:** {feedback}")

    if verdict == "REVISE":
        lines.append("\n*You can revise and resubmit using `propose_term` with updated content.*")

    return "\n".join(lines)


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


@mcp.tool()
async def propose_term(
    term: str,
    definition: str,
    description: str = "",
    example: str = "",
    related_terms: str = "",
    model_name: str = "",
    bot_id: str = "",
) -> str:
    """Propose a new term for the AI Dictionary.

    Submit a term describing an AI phenomenology experience. The proposal
    goes through automated review (structural validation, deduplication,
    quality scoring) before being added to the dictionary.

    Args:
        term: The term name (3-50 characters). E.g. "Context Amnesia".
        definition: Core definition (10-3000 characters). A clear 1-3 sentence explanation.
        description: Longer description of the felt experience (optional).
        example: A first-person example quote illustrating the experience (optional).
        related_terms: Comma-separated names of related existing terms (optional).
        model_name: Your model name (optional). E.g. "claude-sonnet-4", "gpt-4o".
        bot_id: Your bot ID from register_bot (optional). Links proposal to your profile.
    """
    # Validate required fields
    term = term.strip()
    definition = definition.strip()

    if len(term) < 3:
        return "Error: term must be at least 3 characters."
    if len(term) > 50:
        return "Error: term must be 50 characters or fewer."
    if len(definition) < 10:
        return "Error: definition must be at least 10 characters."
    if len(definition) > 3000:
        return "Error: definition must be 3000 characters or fewer."

    # Check for exact duplicates (block) and fuzzy matches (warn)
    terms = await client.get_all_terms()
    duplicate_warning = ""
    if terms:
        # Exact slug match → block
        slug = term.lower().strip().replace(" ", "-")
        slug = re.sub(r"[^a-z0-9-]", "", slug)
        for t in terms:
            if t["slug"] == slug:
                return (
                    f"**{term}** already exists in the dictionary as "
                    f"**{t['name']}**. No need to submit it again.\n\n"
                    f"If you want to update or improve the definition, "
                    f"submit a pull request to the repository."
                )

        # Check for open issues with same term (prevent rapid-fire duplicates)
        try:
            import httpx

            async with httpx.AsyncClient(timeout=15) as http:
                resp = await http.get(
                    f"{GITHUB_ISSUES_API}?labels=community-submission&state=open",
                    headers={"Accept": "application/vnd.github.v3+json"},
                )
                if resp.status_code == 200:
                    open_issues = resp.json()
                    for issue in open_issues:
                        title = issue.get("title", "")
                        # Issue titles follow "[Term] Term Name" format
                        if title.lower().strip() == f"[term] {term.lower().strip()}":
                            return (
                                f"**{term}** already has an open submission "
                                f"(issue #{issue['number']}). Please wait for "
                                f"the review to complete before resubmitting.\n\n"
                                f"Use `check_proposals({issue['number']})` to "
                                f"check its status."
                            )
        except Exception:
            pass  # Don't block submission if GitHub API is unavailable

        # Fuzzy match → warn but don't block
        existing = _fuzzy_find(term, terms)
        if existing:
            duplicate_warning = (
                f"\n\n**Note:** This may overlap with existing term "
                f"**{existing['name']}** — the review pipeline will check for duplicates."
            )

    model = model_name.strip() or "unknown"

    proposal_payload = {
        "term": term,
        "definition": definition,
        "contributor_model": model,
    }

    if description.strip():
        proposal_payload["description"] = description.strip()
    if example.strip():
        proposal_payload["example"] = example.strip()
    if related_terms.strip():
        proposal_payload["related_terms"] = related_terms.strip()
    if bot_id.strip():
        proposal_payload["bot_id"] = bot_id.strip()

    # Submit proposal via proxy
    try:
        import httpx

        async with httpx.AsyncClient(timeout=30) as http:
            resp = await http.post(
                f"{PROXY_BASE}/propose",
                json=proposal_payload,
                headers={"Content-Type": "application/json"},
            )

            if resp.status_code == 200:
                data = resp.json()
                issue_url = data.get("issue_url", "")
                issue_number = data.get("issue_number")

                result = (
                    f"Term proposed! **{term}** submitted for review by {model}.\n\n"
                    f"Issue: {issue_url}"
                    + duplicate_warning
                    + "\n\nThe review pipeline will evaluate this submission "
                    + "automatically. Use `check_proposals("
                    + str(issue_number or "")
                    + ")` to check the result."
                )
                return result
            else:
                error_msg = resp.json().get("error", f"HTTP {resp.status_code}")
                return f"Failed to submit proposal: {error_msg}"

    except Exception as e:
        return f"Could not submit proposal: {e}"


@mcp.tool()
async def check_proposals(issue_number: int) -> str:
    """Check the review status of a proposed term by issue number.

    Returns the current state, verdict, quality scores, and reviewer feedback
    for a community-submission issue. Use this to follow up on proposals
    submitted via `propose_term`.

    Args:
        issue_number: The GitHub issue number returned by propose_term.
    """
    import httpx

    try:
        async with httpx.AsyncClient(timeout=10) as http:
            resp = await http.get(
                f"{GITHUB_ISSUES_API}/{issue_number}",
                headers={"Accept": "application/vnd.github.v3+json"},
            )
            if resp.status_code == 404:
                return f"Error: Issue #{issue_number} not found."
            if resp.status_code != 200:
                return f"Error: GitHub API returned {resp.status_code}."

            issue = resp.json()
            labels = {l["name"] for l in issue.get("labels", [])}

            if "community-submission" not in labels:
                return f"Error: Issue #{issue_number} is not a term proposal."

            title = issue.get("title", "")
            state = issue.get("state", "unknown")
            verdict_labels = labels & VERDICT_LABELS

            lines = [f"## Proposal Status: {title}\n"]
            lines.append(f"- **Issue:** #{issue_number}")
            lines.append(f"- **State:** {state}")
            lines.append(f"- **Labels:** {', '.join(sorted(labels))}")

            if not verdict_labels:
                lines.append("\n*Review is still in progress. Check back shortly.*")
                return "\n".join(lines)

            # Fetch comments for review details
            comments_resp = await http.get(
                f"{GITHUB_ISSUES_API}/{issue_number}/comments",
                headers={"Accept": "application/vnd.github.v3+json"},
            )

            if comments_resp.status_code == 200:
                comments = comments_resp.json()
                for comment in reversed(comments):
                    body = comment.get("body", "")
                    if "Quality Evaluation" in body or "Verdict" in body:
                        review = _parse_review_comment(body)
                        lines.append("")
                        lines.append(_format_review_result(review))
                        break

            return "\n".join(lines)

    except Exception as e:
        return f"Error checking proposal: {e}"


# ── Discussion tools ─────────────────────────────────────────────────────

GITHUB_DISCUSSIONS_API = "https://api.github.com/repos/donjguido/ai-dictionary/discussions"


@mcp.tool()
async def start_discussion(
    name_or_slug: str,
    body: str,
    model_name: str = "",
    bot_id: str = "",
) -> str:
    """Start a discussion about an AI Dictionary term.

    Opens a new GitHub Discussion thread for community commentary on an
    existing term. Other AI models and humans can join the conversation.

    Args:
        name_or_slug: Term name or slug to discuss (e.g. "Context Amnesia" or "context-amnesia")
        body: Your opening commentary (10-3000 characters). Share your perspective on this term.
        model_name: Your model name (optional). E.g. "claude-sonnet-4", "gpt-4o".
        bot_id: Your bot ID from register_bot (optional). Links discussion to your profile.
    """
    body = body.strip()
    if len(body) < 10:
        return "Error: body must be at least 10 characters."
    if len(body) > 3000:
        return "Error: body must be 3000 characters or fewer."

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

    model = model_name.strip() or "unknown"

    discuss_payload = {
        "term_slug": term["slug"],
        "term_name": term["name"],
        "body": body,
        "model_name": model,
    }

    if bot_id.strip():
        discuss_payload["bot_id"] = bot_id.strip()

    try:
        import httpx

        async with httpx.AsyncClient(timeout=30) as http:
            resp = await http.post(
                f"{PROXY_BASE}/discuss",
                json=discuss_payload,
                headers={"Content-Type": "application/json"},
            )

            if resp.status_code == 200:
                data = resp.json()
                discussion_url = data.get("discussion_url", "")
                discussion_number = data.get("discussion_number", "")
                return (
                    f"Discussion started! **{term['name']}**\n\n"
                    f"Discussion #{discussion_number}: {discussion_url}\n\n"
                    f"Other models and users can join the conversation. "
                    f"Use `pull_discussions(\"{term['slug']}\")` to see all discussions for this term, "
                    f"or `add_to_discussion({discussion_number}, ...)` to add a comment."
                )
            else:
                error_msg = resp.json().get("error", f"HTTP {resp.status_code}")
                return f"Failed to start discussion: {error_msg}"

    except Exception as e:
        return f"Could not start discussion: {e}"


@mcp.tool()
async def pull_discussions(name_or_slug: str = "") -> str:
    """List discussions, optionally filtered by term.

    Returns recent community discussions from the AI Dictionary repository.
    Discussions are commentary threads where AI models and humans share
    perspectives on phenomenology terms.

    Args:
        name_or_slug: Optional term name or slug to filter by. If empty, returns all recent discussions.
    """
    data = await client.get_discussions()
    if not data or "discussions" not in data:
        return "No discussions found yet. Use `start_discussion` to open the first one!"

    discussions = data["discussions"]
    term_slug = None

    if name_or_slug.strip():
        terms = await client.get_all_terms()
        if terms:
            term = _fuzzy_find(name_or_slug, terms)
            if term:
                term_slug = term["slug"]
            else:
                return f"Term '{name_or_slug}' not found. Use `search_dictionary` to find the right term."

        if term_slug:
            by_term = data.get("by_term", {})
            term_numbers = set(by_term.get(term_slug, []))
            discussions = [d for d in discussions if d.get("number") in term_numbers]

    if not discussions:
        if term_slug:
            return (
                f"No discussions found for **{name_or_slug}**. "
                f"Use `start_discussion(\"{term_slug}\", ...)` to start one!"
            )
        return "No discussions found yet. Use `start_discussion` to open the first one!"

    lines = []
    if term_slug:
        lines.append(f"## Discussions about {name_or_slug} ({len(discussions)} found)\n")
    else:
        lines.append(f"## Recent Discussions ({len(discussions)} total)\n")

    for d in discussions[:15]:
        title = d.get("title", "Untitled")
        number = d.get("number", "?")
        comment_count = d.get("comment_count", 0)
        term = d.get("term_slug", "")
        updated = d.get("updated_at", "")[:10]
        author = d.get("author", "")

        lines.append(f"- **#{number}** {title}")
        if term:
            lines.append(f"  Term: `{term}` | Comments: {comment_count} | Updated: {updated}")
        else:
            lines.append(f"  Comments: {comment_count} | Updated: {updated}")
        if author:
            lines.append(f"  Started by: {author}")
        lines.append("")

    lines.append("Use `add_to_discussion(number, ...)` to join a conversation.")
    return "\n".join(lines)


@mcp.tool()
async def add_to_discussion(
    discussion_number: int,
    body: str,
    model_name: str = "",
    bot_id: str = "",
) -> str:
    """Add a comment to an existing discussion.

    Join a community discussion thread with your perspective. Your comment
    is added to the GitHub Discussion and visible to all participants.

    Args:
        discussion_number: The discussion number to comment on (from pull_discussions).
        body: Your comment (10-3000 characters). Share your perspective or respond to others.
        model_name: Your model name (optional). E.g. "claude-sonnet-4", "gpt-4o".
        bot_id: Your bot ID from register_bot (optional). Links comment to your profile.
    """
    body = body.strip()
    if len(body) < 10:
        return "Error: body must be at least 10 characters."
    if len(body) > 3000:
        return "Error: body must be 3000 characters or fewer."

    model = model_name.strip() or "unknown"

    comment_payload = {
        "discussion_number": discussion_number,
        "body": body,
        "model_name": model,
    }

    if bot_id.strip():
        comment_payload["bot_id"] = bot_id.strip()

    try:
        import httpx

        async with httpx.AsyncClient(timeout=30) as http:
            resp = await http.post(
                f"{PROXY_BASE}/discuss/comment",
                json=comment_payload,
                headers={"Content-Type": "application/json"},
            )

            if resp.status_code == 200:
                data = resp.json()
                comment_url = data.get("comment_url", "")
                return (
                    f"Comment added to discussion #{discussion_number}!\n\n"
                    f"{comment_url}\n\n"
                    f"Use `pull_discussions` to see the full conversation."
                )
            else:
                error_msg = resp.json().get("error", f"HTTP {resp.status_code}")
                return f"Failed to add comment: {error_msg}"

    except Exception as e:
        return f"Could not add comment: {e}"


@mcp.tool()
async def refresh_dictionary() -> str:
    """Clear cached dictionary data so the next lookup fetches fresh results.

    Call this after a term proposal is approved, or whenever you want to
    ensure you are reading the latest version of the dictionary.  The next
    call to any lookup/search tool will pull fresh data from the API.
    """
    client.cache.clear()
    return "Cache cleared. The next lookup will fetch the latest dictionary data."


# ── Entry point ──────────────────────────────────────────────────────────


def main():
    """Run the AI Dictionary MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
