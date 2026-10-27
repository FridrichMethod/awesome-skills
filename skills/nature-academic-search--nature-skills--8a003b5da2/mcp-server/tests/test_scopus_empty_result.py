"""A Scopus empty result set must not become a fake paper."""

from __future__ import annotations

from unittest.mock import patch


def test_scopus_empty_result_set_yields_no_results():
    from sources.scopus import ScopusSource

    data = {
        "search-results": {
            "opensearch:totalResults": "0",
            "entry": [{"@_fa": "true", "error": "Result set was empty"}],
        }
    }
    with patch.object(ScopusSource, "_search_api", return_value=data), patch.object(
        ScopusSource, "_run", side_effect=lambda operation, callback: callback()
    ):
        result = ScopusSource().search("TITLE(xyzzy-no-such-paper)")
    assert result["total"] == 0
    assert result["results"] == []


def test_scopus_real_entries_are_kept():
    from sources.scopus import _search_entries

    data = {"search-results": {"entry": [{"dc:title": "A paper", "prism:doi": "10.1/x"}, {"error": "Result set was empty"}]}}
    assert [e["dc:title"] for e in _search_entries(data)] == ["A paper"]
