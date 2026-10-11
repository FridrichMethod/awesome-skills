"""Error and missing-data handling for citation output (no network access)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from utils.errors import DataSourceError


def _crossref_config():
    cfg = MagicMock()
    cfg.crossref_mailto = "test@example.com"
    cfg.crossref_timeout = 10
    return cfg


@patch("sources.crossref.get_config")
@patch("sources.crossref.requests.get")
def test_crossref_404_raises_instead_of_returning_a_fake_citation(mock_get, mock_config):
    mock_config.return_value = _crossref_config()
    mock_get.return_value = MagicMock(status_code=404)

    from sources.crossref import CrossRefSource

    with pytest.raises(DataSourceError, match="10.9999/nope"):
        CrossRefSource().get_citation("10.9999/nope", style="apa")


@patch("academic_search_server._crossref")
def test_get_citation_tool_reports_an_error_for_an_unknown_doi(mock_crossref):
    mock_crossref.get_citation.side_effect = DataSourceError("crossref", "No citation found for DOI 10.9999/nope")

    import academic_search_server

    payload = json.loads(academic_search_server.get_citation("10.9999/nope", id_type="doi"))
    assert "citation" not in payload
    assert "error" in json.dumps(payload).lower()


def test_basic_citation_uses_nd_when_year_is_none():
    import academic_search_server

    paper = {"authors": ["Smith J"], "title": "T", "year": None, "journal": None, "doi": None, "pmid": "123"}
    for style in ("apa", "vancouver", "ieee", "nature"):
        citation = academic_search_server._format_basic_citation(paper, style)
        assert "None" not in citation, (style, citation)
