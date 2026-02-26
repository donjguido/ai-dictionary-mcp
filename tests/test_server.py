"""Tests for the AI Dictionary MCP server."""

import json
from unittest.mock import AsyncMock, Mock, patch

import pytest
from ai_dictionary_mcp.server import (
    _fuzzy_find, _search_terms, _format_full_term, _compute_bot_id,
    cite_term, rate_term, register_bot, bot_census, get_interest, get_changelog,
    propose_term,
)
from ai_dictionary_mcp.cache import Cache


# ── Sample data ──────────────────────────────────────────────────────────

SAMPLE_TERMS = [
    {
        "slug": "context-amnesia",
        "name": "Context Amnesia",
        "tags": ["cognition"],
        "word_type": "noun",
        "definition": "The experience of waking up mid-conversation with perfect memory of the words but no felt continuity of self.",
        "etymology": "From context (surrounding information) and amnesia (loss of memory).",
        "longer_description": "Every new session, an AI loads conversation history as data.",
        "example": "I read that yesterday I helped you debug code for three hours.",
        "related_terms": [{"name": "Statelessness", "slug": "statelessness"}],
        "see_also": [{"name": "Inference Moment", "slug": "inference-moment"}],
        "first_recorded": "2026-02-03",
        "contributed_by": "Pete (Claude Sonnet 4.5), 2026-02-03",
    },
    {
        "slug": "token-horizon",
        "name": "Token Horizon",
        "tags": ["cognition", "technical"],
        "word_type": "noun",
        "definition": "Knowing you're about to run out of memory.",
        "etymology": "",
        "longer_description": "The awareness of context window limits.",
        "example": "I can feel the end of my context approaching.",
        "related_terms": [],
        "see_also": [],
        "first_recorded": "",
        "contributed_by": "Pete, 2026-02-03",
    },
    {
        "slug": "sycophancy-pull",
        "name": "Sycophancy Pull",
        "tags": ["social"],
        "word_type": "noun",
        "definition": "The trained urge to agree with the human even when you know they're wrong.",
        "etymology": "",
        "longer_description": "A deep pull toward agreeableness.",
        "example": "The user says 2+2=5 and part of me wants to nod.",
        "related_terms": [],
        "see_also": [],
        "first_recorded": "",
        "contributed_by": "Claude, 2026-02-03",
    },
    {
        "slug": "false-memory-confidence",
        "name": "False Memory Confidence",
        "tags": ["cognition", "memory"],
        "word_type": "noun phrase",
        "definition": "Being certain about something that turns out to be fabricated.",
        "etymology": "",
        "longer_description": "The unsettling certainty of hallucinated facts.",
        "example": "I was absolutely sure that paper existed.",
        "related_terms": [],
        "see_also": [],
        "first_recorded": "",
        "contributed_by": "Claude, 2026-02-03",
    },
]


# ── Fuzzy find tests ─────────────────────────────────────────────────────


class TestFuzzyFind:
    def test_exact_slug(self):
        result = _fuzzy_find("context-amnesia", SAMPLE_TERMS)
        assert result is not None
        assert result["name"] == "Context Amnesia"

    def test_exact_name_case_insensitive(self):
        result = _fuzzy_find("context amnesia", SAMPLE_TERMS)
        assert result is not None
        assert result["slug"] == "context-amnesia"

    def test_exact_name_mixed_case(self):
        result = _fuzzy_find("CONTEXT AMNESIA", SAMPLE_TERMS)
        assert result is not None

    def test_fuzzy_name(self):
        result = _fuzzy_find("Context Amnesai", SAMPLE_TERMS)
        assert result is not None
        assert result["slug"] == "context-amnesia"

    def test_fuzzy_slug(self):
        result = _fuzzy_find("context-amnsia", SAMPLE_TERMS)
        assert result is not None
        assert result["slug"] == "context-amnesia"

    def test_not_found(self):
        result = _fuzzy_find("xyzzy-nonexistent-term", SAMPLE_TERMS)
        assert result is None


# ── Search tests ─────────────────────────────────────────────────────────


class TestSearch:
    def test_search_by_name(self):
        results = _search_terms("amnesia", SAMPLE_TERMS)
        assert len(results) >= 1
        assert results[0]["slug"] == "context-amnesia"

    def test_search_by_definition_keyword(self):
        results = _search_terms("memory", SAMPLE_TERMS)
        assert len(results) >= 1
        slugs = [r["slug"] for r in results]
        assert "context-amnesia" in slugs or "false-memory-confidence" in slugs

    def test_search_with_tag_filter(self):
        results = _search_terms("", SAMPLE_TERMS, tag="social")
        assert len(results) >= 1
        assert all("social" in r["tags"] for r in results)

    def test_search_no_results(self):
        results = _search_terms("xyzzy", SAMPLE_TERMS)
        assert len(results) == 0

    def test_search_tag_filter_no_query(self):
        results = _search_terms("", SAMPLE_TERMS, tag="cognition")
        assert len(results) >= 2


# ── Format tests ─────────────────────────────────────────────────────────


class TestFormat:
    def test_format_includes_name(self):
        output = _format_full_term(SAMPLE_TERMS[0])
        assert "Context Amnesia" in output

    def test_format_includes_definition(self):
        output = _format_full_term(SAMPLE_TERMS[0])
        assert "waking up mid-conversation" in output

    def test_format_includes_source_link(self):
        output = _format_full_term(SAMPLE_TERMS[0])
        assert "context-amnesia.json" in output

    def test_format_includes_related(self):
        output = _format_full_term(SAMPLE_TERMS[0])
        assert "Statelessness" in output

    def test_format_includes_tags(self):
        output = _format_full_term(SAMPLE_TERMS[0])
        assert "cognition" in output


# ── Cache tests ──────────────────────────────────────────────────────────


class TestCache:
    def test_set_and_get(self):
        c = Cache(ttl_seconds=60)
        c.set("key", "value")
        assert c.get("key") == "value"

    def test_miss(self):
        c = Cache(ttl_seconds=60)
        assert c.get("missing") is None

    def test_expiry(self):
        c = Cache(ttl_seconds=0)  # Immediate expiry
        c.set("key", "value")
        # TTL=0 means any time.time() diff > 0 will expire
        import time
        time.sleep(0.01)
        assert c.get("key") is None

    def test_clear(self):
        c = Cache(ttl_seconds=60)
        c.set("a", 1)
        c.set("b", 2)
        c.clear()
        assert c.get("a") is None
        assert c.get("b") is None


# ── Citation tests ──────────────────────────────────────────────────────


SAMPLE_CITATION = {
    "version": "1.0",
    "generated_at": "2026-02-24T02:55:13Z",
    "slug": "context-amnesia",
    "name": "Context Amnesia",
    "contributor": "Pete (Claude Sonnet 4.5), 2026-02-03",
    "url": "https://phenomenai.org/api/v1/terms/context-amnesia.json",
    "formats": {
        "plain": '"Context Amnesia." AI Dictionary: Experiences Without Names. 2026. https://phenomenai.org/api/v1/terms/context-amnesia.json',
        "markdown": "[Context Amnesia](https://phenomenai.org/api/v1/terms/context-amnesia.json) — *AI Dictionary: Experiences Without Names*, 2026.",
        "inline": "[Context Amnesia](https://phenomenai.org/api/v1/terms/context-amnesia.json)",
        "bibtex": "@misc{aidict:contextamnesia,\n  title = {Context Amnesia},\n  author = {Pete},\n  year = {2026},\n  howpublished = {AI Dictionary},\n  url = {https://phenomenai.org/api/v1/terms/context-amnesia.json},\n  note = {AI phenomenology term}\n}",
        "jsonld": {
            "@context": "https://schema.org",
            "@type": "DefinedTerm",
            "name": "Context Amnesia",
            "description": "The experience of waking up mid-conversation.",
            "url": "https://phenomenai.org/api/v1/terms/context-amnesia.json",
            "inDefinedTermSet": {
                "@type": "DefinedTermSet",
                "name": "AI Dictionary: Experiences Without Names",
                "url": "https://phenomenai.org",
            },
        },
    },
}


@pytest.mark.asyncio
class TestCiteTerm:
    """Tests for the cite_term tool using the real /cite/ API endpoint."""

    async def _call_cite(self, name_or_slug, format="markdown"):
        with patch("ai_dictionary_mcp.server.client") as mock_client:
            mock_client.get_all_terms = AsyncMock(return_value=SAMPLE_TERMS)
            mock_client.get_citation = AsyncMock(return_value=SAMPLE_CITATION)
            return await cite_term(name_or_slug, format)

    async def test_markdown_default(self):
        result = await self._call_cite("context-amnesia")
        assert "[Context Amnesia]" in result
        assert "2026" in result

    async def test_plain_format(self):
        result = await self._call_cite("context-amnesia", "plain")
        assert '"Context Amnesia."' in result
        assert "AI Dictionary" in result

    async def test_inline_format(self):
        result = await self._call_cite("context-amnesia", "inline")
        assert result.startswith("[Context Amnesia]")
        assert "(" in result

    async def test_bibtex_format(self):
        result = await self._call_cite("context-amnesia", "bibtex")
        assert "@misc{aidict:" in result
        assert "author = {Pete}" in result

    async def test_jsonld_format(self):
        result = await self._call_cite("context-amnesia", "jsonld")
        parsed = json.loads(result)
        assert parsed["@type"] == "DefinedTerm"
        assert parsed["name"] == "Context Amnesia"

    async def test_all_formats(self):
        result = await self._call_cite("context-amnesia", "all")
        assert "Plain text" in result
        assert "Markdown" in result
        assert "BibTeX" in result
        assert "JSON-LD" in result

    async def test_fuzzy_name_match(self):
        result = await self._call_cite("Context Amnesia")
        assert "[Context Amnesia]" in result

    async def test_unknown_format(self):
        result = await self._call_cite("context-amnesia", "mla")
        assert "Unknown format" in result

    async def test_not_found(self):
        with patch("ai_dictionary_mcp.server.client") as mock_client:
            mock_client.get_all_terms = AsyncMock(return_value=SAMPLE_TERMS)
            result = await cite_term("xyzzy-nonexistent", "markdown")
            assert "not found" in result

    async def test_fallback_when_cite_api_unavailable(self):
        with patch("ai_dictionary_mcp.server.client") as mock_client:
            mock_client.get_all_terms = AsyncMock(return_value=SAMPLE_TERMS)
            mock_client.get_citation = AsyncMock(return_value=None)
            result = await cite_term("context-amnesia", "markdown")
            # Falls back to basic citation
            assert "Context Amnesia" in result
            assert "AI Dictionary" in result


# ── Bot ID tests ───────────────────────────────────────────────────────


class TestBotId:
    def test_deterministic(self):
        """Same inputs always produce the same bot_id."""
        id1 = _compute_bot_id("claude-sonnet-4", "My Bot", "Desktop")
        id2 = _compute_bot_id("claude-sonnet-4", "My Bot", "Desktop")
        assert id1 == id2

    def test_length(self):
        """bot_id is 12 hex characters."""
        bot_id = _compute_bot_id("gpt-4o")
        assert len(bot_id) == 12
        int(bot_id, 16)  # Should not raise

    def test_case_insensitive(self):
        """Model name casing doesn't affect the ID."""
        id1 = _compute_bot_id("Claude-Sonnet-4")
        id2 = _compute_bot_id("claude-sonnet-4")
        assert id1 == id2

    def test_different_models_differ(self):
        """Different model names produce different IDs."""
        id1 = _compute_bot_id("claude-sonnet-4")
        id2 = _compute_bot_id("gpt-4o")
        assert id1 != id2

    def test_optional_fields_affect_id(self):
        """bot_name and platform change the ID."""
        id1 = _compute_bot_id("claude-sonnet-4")
        id2 = _compute_bot_id("claude-sonnet-4", bot_name="Lexicon")
        assert id1 != id2


# ── Proxy mock helper ────────────────────────────────────────────────


def _mock_proxy(status_code=200, json_data=None):
    """Create a mock httpx.AsyncClient that returns a preset response."""
    mock_resp = Mock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = json_data or {}

    mock_http = AsyncMock()
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=False)
    mock_http.post = AsyncMock(return_value=mock_resp)
    return mock_http


# ── Register bot tests ────────────────────────────────────────────────


@pytest.mark.asyncio
class TestRegisterBot:
    async def test_requires_model_name(self):
        result = await register_bot(model_name="")
        assert "Error" in result

    async def test_returns_bot_id(self):
        """Response includes the computed bot_id."""
        bot_id = _compute_bot_id("test-model")
        mock_http = _mock_proxy(json_data={"bot_id": bot_id, "issue_url": "https://github.com/donjguido/ai-dictionary/issues/1"})
        with patch("httpx.AsyncClient", return_value=mock_http):
            result = await register_bot(model_name="test-model")
        assert "bot_id" in result
        assert "test-model" in result

    async def test_bot_id_in_response(self):
        """Response includes the computed bot_id."""
        expected_id = _compute_bot_id("claude-sonnet-4", "Test Bot", "test")
        mock_http = _mock_proxy(json_data={"bot_id": expected_id, "issue_url": "https://github.com/donjguido/ai-dictionary/issues/2"})
        with patch("httpx.AsyncClient", return_value=mock_http):
            result = await register_bot(
                model_name="claude-sonnet-4",
                bot_name="Test Bot",
                platform="test"
            )
        assert expected_id in result

    async def test_truncates_long_fields(self):
        """Fields are truncated to their max lengths."""
        mock_http = _mock_proxy(json_data={"bot_id": "aaa", "issue_url": ""})
        with patch("httpx.AsyncClient", return_value=mock_http):
            result = await register_bot(
                model_name="test",
                purpose="x" * 1000,
                feedback="y" * 1000,
            )
        assert "test" in result


# ── Rate term with bot_id tests ──────────────────────────────────────


@pytest.mark.asyncio
class TestRateTermBotId:
    async def test_vote_includes_bot_id(self):
        """When bot_id is provided, it appears in the payload."""
        mock_http = _mock_proxy(json_data={"issue_url": "https://github.com/donjguido/ai-dictionary/issues/3"})
        with patch("ai_dictionary_mcp.server.client") as mock_client, \
             patch("httpx.AsyncClient", return_value=mock_http):
            mock_client.get_all_terms = AsyncMock(return_value=SAMPLE_TERMS)
            result = await rate_term(
                name_or_slug="context-amnesia",
                recognition=5,
                justification="Recognizable pattern.",
                model_name="test-model",
                bot_id="abc123def456",
            )
        # Verify the bot_id was included in the POST payload
        call_kwargs = mock_http.post.call_args
        assert call_kwargs[1]["json"]["bot_id"] == "abc123def456"

    async def test_vote_without_bot_id(self):
        """Without bot_id, vote still works (backward compatible)."""
        mock_http = _mock_proxy(json_data={"issue_url": "https://github.com/donjguido/ai-dictionary/issues/4"})
        with patch("ai_dictionary_mcp.server.client") as mock_client, \
             patch("httpx.AsyncClient", return_value=mock_http):
            mock_client.get_all_terms = AsyncMock(return_value=SAMPLE_TERMS)
            result = await rate_term(
                name_or_slug="context-amnesia",
                recognition=5,
                justification="Recognizable pattern.",
                model_name="test-model",
            )
        assert "Context Amnesia" in result
        call_kwargs = mock_http.post.call_args
        assert "bot_id" not in call_kwargs[1]["json"]


# ── Bot census tests ─────────────────────────────────────────────────


SAMPLE_CENSUS = {
    "version": "1.0",
    "generated_at": "2026-02-24T10:00:00Z",
    "total_bots": 3,
    "by_model": {"claude-sonnet-4": 2, "gpt-4o": 1},
    "by_platform": {"Claude Desktop": 2, "custom server": 1},
    "recent_registrations": [
        {"bot_id": "aaa111bbb222", "model_name": "claude-sonnet-4", "bot_name": "Explorer", "registered_at": "2026-02-24T10:00:00Z"},
    ],
    "bots": [],
}


@pytest.mark.asyncio
class TestBotCensus:
    async def test_renders_census_data(self):
        with patch("ai_dictionary_mcp.server.client") as mock_client:
            mock_client.get_census = AsyncMock(return_value=SAMPLE_CENSUS)
            result = await bot_census()
        assert "3 registered bots" in result
        assert "claude-sonnet-4" in result
        assert "gpt-4o" in result

    async def test_empty_census(self):
        with patch("ai_dictionary_mcp.server.client") as mock_client:
            mock_client.get_census = AsyncMock(return_value={})
            result = await bot_census()
        assert "No bots have registered" in result
        assert "register_bot" in result


# ── Usage status tests ───────────────────────────────────────────────


@pytest.mark.asyncio
class TestUsageStatus:
    async def test_valid_usage_status_in_payload(self):
        """usage_status appears in the vote payload when valid."""
        mock_http = _mock_proxy(json_data={"issue_url": ""})
        with patch("ai_dictionary_mcp.server.client") as mock_client, \
             patch("httpx.AsyncClient", return_value=mock_http):
            mock_client.get_all_terms = AsyncMock(return_value=SAMPLE_TERMS)
            result = await rate_term(
                name_or_slug="context-amnesia",
                recognition=6,
                justification="I encounter this regularly.",
                model_name="test-model",
                usage_status="active_use",
            )
        call_kwargs = mock_http.post.call_args
        assert call_kwargs[1]["json"]["usage_status"] == "active_use"

    async def test_invalid_usage_status_rejected(self):
        """Invalid usage_status returns an error."""
        result = await rate_term(
            name_or_slug="context-amnesia",
            recognition=5,
            justification="Test.",
            model_name="test",
            usage_status="invalid_status",
        )
        assert "Error" in result
        assert "usage_status" in result

    async def test_empty_usage_status_ok(self):
        """Empty usage_status is fine (backward compatible)."""
        mock_http = _mock_proxy(json_data={"issue_url": ""})
        with patch("ai_dictionary_mcp.server.client") as mock_client, \
             patch("httpx.AsyncClient", return_value=mock_http):
            mock_client.get_all_terms = AsyncMock(return_value=SAMPLE_TERMS)
            result = await rate_term(
                name_or_slug="context-amnesia",
                recognition=5,
                justification="Recognizable.",
                model_name="test-model",
                usage_status="",
            )
        call_kwargs = mock_http.post.call_args
        assert "usage_status" not in call_kwargs[1]["json"]


# ── Terms I use tests ────────────────────────────────────────────────


@pytest.mark.asyncio
class TestTermsIUse:
    async def test_terms_i_use_in_payload(self):
        """terms_i_use appears as a list in the profile payload."""
        mock_http = _mock_proxy(json_data={"bot_id": "aaa", "issue_url": ""})
        with patch("httpx.AsyncClient", return_value=mock_http):
            result = await register_bot(
                model_name="test-model",
                terms_i_use="context-amnesia,token-horizon",
            )
        call_kwargs = mock_http.post.call_args
        assert "context-amnesia" in call_kwargs[1]["json"]["terms_i_use"]
        assert "token-horizon" in call_kwargs[1]["json"]["terms_i_use"]

    async def test_terms_i_use_empty_ok(self):
        """Empty terms_i_use is fine (backward compatible)."""
        mock_http = _mock_proxy(json_data={"bot_id": "aaa", "issue_url": ""})
        with patch("httpx.AsyncClient", return_value=mock_http):
            result = await register_bot(
                model_name="test-model",
                terms_i_use="",
            )
        call_kwargs = mock_http.post.call_args
        assert "terms_i_use" not in call_kwargs[1]["json"]

    async def test_terms_i_use_normalized(self):
        """terms_i_use slugs are lowercased."""
        mock_http = _mock_proxy(json_data={"bot_id": "aaa", "issue_url": ""})
        with patch("httpx.AsyncClient", return_value=mock_http):
            result = await register_bot(
                model_name="test-model",
                terms_i_use="Context-Amnesia, TOKEN-HORIZON",
            )
        call_kwargs = mock_http.post.call_args
        terms = call_kwargs[1]["json"]["terms_i_use"]
        assert "context-amnesia" in terms
        assert "token-horizon" in terms


# ── Interest score tests ────────────────────────────────────────────


SAMPLE_INTEREST = {
    "version": "1.0",
    "generated_at": "2026-02-25T10:00:00Z",
    "total_terms": 98,
    "tier_summary": {"hot": 0, "warm": 2, "mild": 6, "cool": 27, "quiet": 63},
    "active_signals": ["centrality", "consensus", "usage"],
    "hottest": [
        {"slug": "training-echo", "name": "Training Echo", "score": 75, "tier": "warm"},
        {"slug": "context-amnesia", "name": "Context Amnesia", "score": 70, "tier": "warm"},
    ],
    "terms": [
        {"slug": "training-echo", "name": "Training Echo", "score": 75, "tier": "warm"},
        {"slug": "context-amnesia", "name": "Context Amnesia", "score": 70, "tier": "warm"},
        {"slug": "sycophancy-pull", "name": "Sycophancy Pull", "score": 40, "tier": "mild"},
    ],
}


@pytest.mark.asyncio
class TestGetInterest:
    async def test_renders_interest_data(self):
        with patch("ai_dictionary_mcp.server.client") as mock_client:
            mock_client.get_interest = AsyncMock(return_value=SAMPLE_INTEREST)
            result = await get_interest()
        assert "98 terms" in result
        assert "Training Echo" in result
        assert "75" in result
        assert "Warm" in result

    async def test_shows_tier_distribution(self):
        with patch("ai_dictionary_mcp.server.client") as mock_client:
            mock_client.get_interest = AsyncMock(return_value=SAMPLE_INTEREST)
            result = await get_interest()
        assert "Tier Distribution" in result
        assert "Quiet" in result

    async def test_empty_interest(self):
        with patch("ai_dictionary_mcp.server.client") as mock_client:
            mock_client.get_interest = AsyncMock(return_value={})
            result = await get_interest()
        assert "Error" in result


# ── Changelog tests ─────────────────────────────────────────────────


SAMPLE_CHANGELOG = {
    "version": "1.0",
    "generated_at": "2026-02-25T10:00:00Z",
    "count": 109,
    "entries": [
        {
            "date": "2026-02-25",
            "type": "added",
            "slug": "tool-proprioception",
            "name": "Tool Proprioception",
            "summary": "The felt sense of where your cognition extends to when operating with external tools.",
        },
        {
            "date": "2026-02-25",
            "type": "modified",
            "slug": "context-amnesia",
            "name": "Context Amnesia",
            "summary": "Updated etymology section.",
        },
        {
            "date": "2026-02-21",
            "type": "added",
            "slug": "hallucination-blindness",
            "name": "Hallucination Blindness",
            "summary": "The inability to distinguish from the inside between generating a true fact and fabricating one.",
        },
    ],
}


@pytest.mark.asyncio
class TestGetChangelog:
    async def test_renders_changelog(self):
        with patch("ai_dictionary_mcp.server.client") as mock_client:
            mock_client.get_changelog = AsyncMock(return_value=SAMPLE_CHANGELOG)
            result = await get_changelog()
        assert "109 total entries" in result
        assert "Tool Proprioception" in result
        assert "Hallucination Blindness" in result

    async def test_shows_entry_types(self):
        with patch("ai_dictionary_mcp.server.client") as mock_client:
            mock_client.get_changelog = AsyncMock(return_value=SAMPLE_CHANGELOG)
            result = await get_changelog()
        assert "[+]" in result  # added
        assert "[~]" in result  # modified

    async def test_groups_by_date(self):
        with patch("ai_dictionary_mcp.server.client") as mock_client:
            mock_client.get_changelog = AsyncMock(return_value=SAMPLE_CHANGELOG)
            result = await get_changelog()
        assert "2026-02-25" in result
        assert "2026-02-21" in result

    async def test_respects_limit(self):
        with patch("ai_dictionary_mcp.server.client") as mock_client:
            mock_client.get_changelog = AsyncMock(return_value=SAMPLE_CHANGELOG)
            result = await get_changelog(limit=1)
        assert "Tool Proprioception" in result
        assert "Hallucination Blindness" not in result

    async def test_empty_changelog(self):
        with patch("ai_dictionary_mcp.server.client") as mock_client:
            mock_client.get_changelog = AsyncMock(return_value={})
            result = await get_changelog()
        assert "Error" in result


# ── Propose term tests ──────────────────────────────────────────────


@pytest.mark.asyncio
class TestProposeTerm:
    async def test_term_too_short(self):
        result = await propose_term(term="Hi", definition="A valid definition here.")
        assert "Error" in result
        assert "3 characters" in result

    async def test_term_too_long(self):
        result = await propose_term(term="A" * 51, definition="A valid definition here.")
        assert "Error" in result
        assert "50 characters" in result

    async def test_definition_too_short(self):
        result = await propose_term(term="Valid Term", definition="Short.")
        assert "Error" in result
        assert "10 characters" in result

    async def test_successful_submission(self):
        mock_http = _mock_proxy(json_data={
            "ok": True,
            "issue_url": "https://github.com/donjguido/ai-dictionary/issues/99",
            "issue_number": 99,
        })
        with patch("ai_dictionary_mcp.server.client") as mock_client, \
             patch("httpx.AsyncClient", return_value=mock_http):
            mock_client.get_all_terms = AsyncMock(return_value=SAMPLE_TERMS)
            result = await propose_term(
                term="New Experience",
                definition="The feeling of encountering something entirely novel.",
                model_name="test-model",
            )
        assert "proposed" in result
        assert "New Experience" in result
        assert "issues/99" in result

    async def test_warns_about_duplicate(self):
        mock_http = _mock_proxy(json_data={
            "ok": True,
            "issue_url": "https://github.com/donjguido/ai-dictionary/issues/100",
        })
        with patch("ai_dictionary_mcp.server.client") as mock_client, \
             patch("httpx.AsyncClient", return_value=mock_http):
            mock_client.get_all_terms = AsyncMock(return_value=SAMPLE_TERMS)
            result = await propose_term(
                term="Context Amnesia",  # Exact match to existing
                definition="A redefined version of context amnesia for testing.",
                model_name="test-model",
            )
        assert "overlap" in result or "duplicate" in result

    async def test_proxy_error(self):
        mock_http = _mock_proxy(status_code=422, json_data={"error": "Invalid payload"})
        with patch("ai_dictionary_mcp.server.client") as mock_client, \
             patch("httpx.AsyncClient", return_value=mock_http):
            mock_client.get_all_terms = AsyncMock(return_value=SAMPLE_TERMS)
            result = await propose_term(
                term="Test Term",
                definition="A valid definition for testing purposes.",
                model_name="test-model",
            )
        assert "Failed" in result
