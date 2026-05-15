from __future__ import annotations

import pytest

from model_eval.resolver import MatchType, resolve_model_names, suggest_similar


@pytest.mark.unit
class TestSuggestSimilar:
    def test_suggests_close_matches(self) -> None:
        known = ["trinity-large-preview", "qwen3-235b-a22b", "qwen3-32b"]
        suggestions = suggest_similar("trinity-large", known)
        assert "trinity-large-preview" in suggestions

    def test_no_matches(self) -> None:
        suggestions = suggest_similar("zzzzz", ["alpha", "beta"])
        assert suggestions == []


KNOWN = [
    "GPT-4o-2024-11-20",
    "Claude 3.5 Sonnet",
    "Gemini-1.5-Pro",
    "OpenAI/o1-preview",
    "Qwen3-235B-A22B",
    "model-x-3.5",
    "model-x-3.6.1",
    "model-x-4.0",
]


@pytest.mark.unit
class TestResolveModelNames:
    def test_exact_match(self) -> None:
        results = resolve_model_names(["GPT-4o-2024-11-20"], KNOWN)
        assert results[0].match_type == MatchType.EXACT
        assert results[0].matched_name == "GPT-4o-2024-11-20"

    def test_case_insensitive(self) -> None:
        results = resolve_model_names(["gpt-4o-2024-11-20"], KNOWN)
        assert results[0].match_type == MatchType.EQUIVALENT
        assert results[0].matched_name == "GPT-4o-2024-11-20"

    def test_org_stripped_user_input(self) -> None:
        results = resolve_model_names(["openai/GPT-4o-2024-11-20"], KNOWN)
        assert results[0].match_type == MatchType.EQUIVALENT
        assert results[0].matched_name == "GPT-4o-2024-11-20"

    def test_org_stripped_known_name(self) -> None:
        results = resolve_model_names(["o1-preview"], KNOWN)
        assert results[0].match_type == MatchType.EQUIVALENT
        assert results[0].matched_name == "OpenAI/o1-preview"

    def test_punctuation_normalized(self) -> None:
        results = resolve_model_names(["Claude-3.5-Sonnet"], KNOWN)
        assert results[0].match_type == MatchType.EQUIVALENT
        assert results[0].matched_name == "Claude 3.5 Sonnet"

    def test_punctuation_underscore(self) -> None:
        results = resolve_model_names(["Claude_3.5_Sonnet"], KNOWN)
        assert results[0].match_type == MatchType.EQUIVALENT
        assert results[0].matched_name == "Claude 3.5 Sonnet"

    def test_version_adjacent_minor(self) -> None:
        results = resolve_model_names(["model-x-3.6"], KNOWN)
        assert results[0].match_type == MatchType.FUZZY
        assert results[0].matched_name in ("model-x-3.5", "model-x-3.6.1")

    def test_version_adjacent_prefers_closest(self) -> None:
        results = resolve_model_names(["model-x-3.7"], KNOWN)
        assert results[0].match_type == MatchType.FUZZY
        assert results[0].matched_name == "model-x-3.6.1"

    def test_normalized_substring(self) -> None:
        results = resolve_model_names(["qwen3235b"], KNOWN)
        assert results[0].match_type == MatchType.FUZZY
        assert results[0].matched_name == "Qwen3-235B-A22B"

    def test_no_match(self) -> None:
        results = resolve_model_names(["nonexistent-model"], KNOWN)
        assert results[0].match_type == MatchType.NONE
        assert results[0].matched_name is None

    def test_multiple_names(self) -> None:
        results = resolve_model_names(
            ["GPT-4o-2024-11-20", "gpt-4o-2024-11-20", "zzzzz"], KNOWN
        )
        assert len(results) == 3
        assert results[0].match_type == MatchType.EXACT
        assert results[1].match_type == MatchType.EQUIVALENT
        assert results[2].match_type == MatchType.NONE

    def test_org_stripped_combined_with_case(self) -> None:
        results = resolve_model_names(["openai/gpt-4o-2024-11-20"], KNOWN)
        assert results[0].match_type == MatchType.EQUIVALENT
        assert results[0].matched_name == "GPT-4o-2024-11-20"

    def test_preserves_user_name(self) -> None:
        results = resolve_model_names(["gpt-4o-2024-11-20"], KNOWN)
        assert results[0].user_name == "gpt-4o-2024-11-20"

    def test_reordered_tokens(self) -> None:
        known = ["qwen2.5 coder instruct 32b"]
        results = resolve_model_names(["qwen2.5-coder-32b-instruct"], known)
        assert results[0].match_type == MatchType.EQUIVALENT
        assert results[0].matched_name == "qwen2.5 coder instruct 32b"
