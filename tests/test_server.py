"""Tests for the AI Dictionary MCP server."""

import pytest
from ai_dictionary_mcp.server import _fuzzy_find, _search_terms, _format_full_term
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
