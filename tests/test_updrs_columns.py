"""Tests for updrs_columns.py — UPDRS-III column name resolution."""
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from updrs_columns import (
    normalize_updrs_column,
    candidate_updrs_columns,
    find_updrs_value,
    valid_updrs_item_total,
)


# ── normalize_updrs_column ──────────────────────────────────────────


class TestNormalizeUpdrsColumn:
    def test_strips_hyphens_and_underscores(self):
        assert normalize_updrs_column("MDSUPDRS_3-1") == "mdsupdrs31"

    def test_strips_spaces(self):
        assert normalize_updrs_column("MDSUPDRS_3 1a") == "mdsupdrs31a"

    def test_lowercases(self):
        assert normalize_updrs_column("MDSUPDRS_3-17E") == "mdsupdrs317e"

    def test_empty_string(self):
        assert normalize_updrs_column("") == ""

    def test_already_normalized(self):
        assert normalize_updrs_column("mdsupdrs31") == "mdsupdrs31"

    def test_special_characters(self):
        assert normalize_updrs_column("MDSUPDRS_3-(1a)") == "mdsupdrs31a"

    def test_numeric_input(self):
        # Should handle numeric input via str() conversion
        assert normalize_updrs_column(42) == "42"


# ── candidate_updrs_columns ─────────────────────────────────────────


class TestCandidateUpdrsColumns:
    def test_no_suffix_returns_base(self):
        result = candidate_updrs_columns(1, None)
        assert result == ["MDSUPDRS_3-1"]

    def test_suffix_a_generates_side_aliases(self):
        result = candidate_updrs_columns(4, "a")
        # suffix "a" has aliases: a, r, right
        normalized = {normalize_updrs_column(c) for c in result}
        assert "mdsupdrs34a" in normalized
        assert "mdsupdrs34r" in normalized
        assert "mdsupdrs34right" in normalized

    def test_suffix_b_generates_left_aliases(self):
        result = candidate_updrs_columns(4, "b")
        normalized = {normalize_updrs_column(c) for c in result}
        assert "mdsupdrs34b" in normalized
        assert "mdsupdrs34l" in normalized
        assert "mdsupdrs34left" in normalized

    def test_item3_has_anatomical_aliases(self):
        # Item 3 (rigidity) has special aliases: neck, RUE, LUE, RLE, LLE
        # Base is "MDSUPDRS_3-3" so normalized includes the item number twice
        result = candidate_updrs_columns(3, "a")
        normalized = {normalize_updrs_column(c) for c in result}
        assert "mdsupdrs33neck" in normalized  # item-specific alias for 3a

    def test_item3b_has_rue_alias(self):
        result = candidate_updrs_columns(3, "b")
        normalized = {normalize_updrs_column(c) for c in result}
        assert "mdsupdrs33rue" in normalized
        assert "mdsupdrs33rightupper" in normalized

    def test_item17_has_anatomical_aliases(self):
        result = candidate_updrs_columns(17, "e")
        normalized = {normalize_updrs_column(c) for c in result}
        assert "mdsupdrs317lipjaw" in normalized
        assert "mdsupdrs317lip" in normalized
        assert "mdsupdrs317jaw" in normalized

    def test_suffix_c_plain(self):
        # Suffix "c" has no side aliases beyond itself
        result = candidate_updrs_columns(5, "c")
        normalized = {normalize_updrs_column(c) for c in result}
        assert "mdsupdrs35c" in normalized

    def test_generates_multiple_separators(self):
        result = candidate_updrs_columns(4, "a")
        # Should generate: MDSUPDRS_3-4a, MDSUPDRS_3-4-a, MDSUPDRS_3-4_a, MDSUPDRS_3-4 a
        base_with_a = [c for c in result if "4" in c and c.endswith("a")]
        assert len(base_with_a) >= 1

    def test_returns_list(self):
        result = candidate_updrs_columns(1, None)
        assert isinstance(result, list)

    def test_no_duplicates(self):
        result = candidate_updrs_columns(3, "a")
        # After normalization there could be dupes, but raw should have unique strings
        assert len(result) == len(set(result))


# ── find_updrs_value ────────────────────────────────────────────────


class TestFindUpdrsValue:
    def test_exact_match(self):
        columns = ["MDSUPDRS_3-1", "MDSUPDRS_3-2", "Age"]
        row = {"MDSUPDRS_3-1": 2.0, "MDSUPDRS_3-2": 3.0, "Age": 65}
        assert find_updrs_value(row, columns, 1, None) == 2.0

    def test_suffix_match(self):
        columns = ["MDSUPDRS_3-4a", "MDSUPDRS_3-4b"]
        row = {"MDSUPDRS_3-4a": 1.0, "MDSUPDRS_3-4b": 2.0}
        assert find_updrs_value(row, columns, 4, "a") == 1.0
        assert find_updrs_value(row, columns, 4, "b") == 2.0

    def test_alias_match_right(self):
        # If data uses "r" instead of "a" for right side
        columns = ["MDSUPDRS_3-4r", "MDSUPDRS_3-4l"]
        row = {"MDSUPDRS_3-4r": 3.0, "MDSUPDRS_3-4l": 1.0}
        assert find_updrs_value(row, columns, 4, "a") == 3.0  # "a" → "r" alias

    def test_underscore_separator(self):
        columns = ["MDSUPDRS_3-4_a"]
        row = {"MDSUPDRS_3-4_a": 2.5}
        assert find_updrs_value(row, columns, 4, "a") == 2.5

    def test_space_separator(self):
        columns = ["MDSUPDRS_3-4 a"]
        row = {"MDSUPDRS_3-4 a": 1.5}
        assert find_updrs_value(row, columns, 4, "a") == 1.5

    def test_missing_returns_none(self):
        columns = ["MDSUPDRS_3-1"]
        row = {"MDSUPDRS_3-1": 2.0}
        assert find_updrs_value(row, columns, 99, None) is None

    def test_nan_returns_none(self):
        import math
        columns = ["MDSUPDRS_3-1"]
        row = {"MDSUPDRS_3-1": float("nan")}
        assert find_updrs_value(row, columns, 1, None) is None

    def test_string_numeric_coerced(self):
        columns = ["MDSUPDRS_3-1"]
        row = {"MDSUPDRS_3-1": "3"}
        assert find_updrs_value(row, columns, 1, None) == 3.0

    def test_non_numeric_string_returns_none(self):
        columns = ["MDSUPDRS_3-1"]
        row = {"MDSUPDRS_3-1": "N/A"}
        assert find_updrs_value(row, columns, 1, None) is None

    def test_invalid_missing_code_returns_none(self):
        columns = ["MDSUPDRS_3-15-R", "MDSUPDRS_3-10"]
        row = {"MDSUPDRS_3-15-R": "9", "MDSUPDRS_3-10": "9"}
        assert find_updrs_value(row, columns, 15, "a") is None
        assert find_updrs_value(row, columns, 10, None) is None

    def test_item3_neck_alias(self):
        columns = ["MDSUPDRS_3-3neck"]
        row = {"MDSUPDRS_3-3neck": 2.0}
        assert find_updrs_value(row, columns, 3, "a") == 2.0

    def test_zero_value(self):
        columns = ["MDSUPDRS_3-1"]
        row = {"MDSUPDRS_3-1": 0}
        assert find_updrs_value(row, columns, 1, None) == 0.0

    def test_returns_float(self):
        columns = ["MDSUPDRS_3-1"]
        row = {"MDSUPDRS_3-1": 2}
        result = find_updrs_value(row, columns, 1, None)
        assert isinstance(result, float)


class TestValidUpdrsItemTotal:
    def test_single_item_total_range(self):
        assert valid_updrs_item_total(9, 4) == 4.0
        assert valid_updrs_item_total(9, 5) is None

    def test_two_side_item_total_range(self):
        assert valid_updrs_item_total(15, 8) == 8.0
        assert valid_updrs_item_total(15, 18) is None

    def test_five_subitem_total_range(self):
        assert valid_updrs_item_total(17, 18) == 18.0
        assert valid_updrs_item_total(17, 21) is None
