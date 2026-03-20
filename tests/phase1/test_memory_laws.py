"""Memory category law tests — Phase 1 seal.

These tests close the gap Ax identified:
  "If it's not tested, it doesn't exist."

Tests the mock memory adapter's enforcement of:
  1. Constitution §5.2.2 — Memory category laws (valid vs invalid categories)
  2. Constitution §5.2.2 HARD LAW — tool_output source restrictions
     (raw tool output must be summarized; only fact/decision/learning allowed)

Run with: pytest tests/phase1/test_memory_laws.py -v
"""

import pytest

from agent_os.adapters.memory.mock_memory import MockMemory, VALID_CATEGORIES


AGENT_ID = "clawbot"


@pytest.fixture
def memory():
    """Fresh mock memory adapter for each test."""
    return MockMemory()


# ── Category validation ───────────────────────────────────────

class TestMemoryCategoryLaws:
    """Verify that invalid memory categories fail fast."""

    def test_valid_category_accepted(self, memory):
        """Writing a valid category (e.g. 'fact') should succeed."""
        entry_id = memory.remember(AGENT_ID, {
            "category": "fact",
            "content": "Leo is based in South Florida.",
            "source": "user_stated",
        })
        assert entry_id is not None
        assert entry_id.startswith("mem_")

    @pytest.mark.parametrize("category", sorted(VALID_CATEGORIES))
    def test_all_valid_categories_accepted(self, memory, category):
        """Every category in the constitution's allowed set should succeed."""
        entry_id = memory.remember(AGENT_ID, {
            "category": category,
            "content": f"Test entry for category '{category}'.",
            "source": "inferred",
        })
        assert entry_id is not None

    def test_invalid_category_rejected(self, memory):
        """Writing an unrecognized category must raise ValueError."""
        with pytest.raises(ValueError, match="Invalid memory category"):
            memory.remember(AGENT_ID, {
                "category": "sensitive",
                "content": "This should never be stored.",
                "source": "inferred",
            })

    def test_empty_category_rejected(self, memory):
        """Empty string category must be rejected."""
        with pytest.raises(ValueError, match="Invalid memory category"):
            memory.remember(AGENT_ID, {
                "category": "",
                "content": "No category provided.",
                "source": "inferred",
            })

    def test_none_category_rejected(self, memory):
        """None category must be rejected."""
        with pytest.raises(ValueError, match="Invalid memory category"):
            memory.remember(AGENT_ID, {
                "category": None,
                "content": "Null category.",
                "source": "inferred",
            })


# ── tool_output hard law ──────────────────────────────────────

class TestToolOutputHardLaw:
    """Constitution HARD LAW: tool_output source can only produce
    fact/decision/learning categories. All others must fail.
    This prevents raw tool output from becoming unprocessed memory."""

    def test_tool_output_as_fact_accepted(self, memory):
        """tool_output → fact is allowed (summarized tool result)."""
        entry_id = memory.remember(AGENT_ID, {
            "category": "fact",
            "content": "Weather is 82°F and sunny in Fort Lauderdale.",
            "source": "tool_output",
        })
        assert entry_id is not None

    def test_tool_output_as_decision_accepted(self, memory):
        """tool_output → decision is allowed."""
        entry_id = memory.remember(AGENT_ID, {
            "category": "decision",
            "content": "Chose OpenRouter fallback after primary model timeout.",
            "source": "tool_output",
        })
        assert entry_id is not None

    def test_tool_output_as_learning_accepted(self, memory):
        """tool_output → learning is allowed."""
        entry_id = memory.remember(AGENT_ID, {
            "category": "learning",
            "content": "wttr.in is blocked on this network; use Open-Meteo.",
            "source": "tool_output",
        })
        assert entry_id is not None

    def test_tool_output_as_event_rejected(self, memory):
        """tool_output → event is NOT allowed (raw ephemeral dump)."""
        with pytest.raises(ValueError, match="tool_output source can only produce"):
            memory.remember(AGENT_ID, {
                "category": "event",
                "content": "Raw API response from Todoist.",
                "source": "tool_output",
            })

    def test_tool_output_as_context_rejected(self, memory):
        """tool_output → context is NOT allowed."""
        with pytest.raises(ValueError, match="tool_output source can only produce"):
            memory.remember(AGENT_ID, {
                "category": "context",
                "content": "Current browser session state.",
                "source": "tool_output",
            })

    def test_tool_output_as_preference_rejected(self, memory):
        """tool_output → preference is NOT allowed
        (preferences come from user, not tools)."""
        with pytest.raises(ValueError, match="tool_output source can only produce"):
            memory.remember(AGENT_ID, {
                "category": "preference",
                "content": "User prefers dark mode.",
                "source": "tool_output",
            })


# ── Source and scope validation ───────────────────────────────

class TestSourceAndScopeValidation:
    """Additional memory contract enforcement."""

    def test_invalid_source_rejected(self, memory):
        """Unrecognized sources must be rejected."""
        with pytest.raises(ValueError, match="Invalid memory source"):
            memory.remember(AGENT_ID, {
                "category": "fact",
                "content": "Something.",
                "source": "magic",
            })

    def test_invalid_scope_rejected(self, memory):
        """Unrecognized scopes must be rejected."""
        with pytest.raises(ValueError, match="Invalid memory scope"):
            memory.remember(AGENT_ID, {
                "category": "fact",
                "content": "Something.",
                "scope": "universe",
            })
