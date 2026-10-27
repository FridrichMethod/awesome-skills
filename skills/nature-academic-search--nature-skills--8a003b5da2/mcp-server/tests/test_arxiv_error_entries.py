"""arXiv error entries must not become fake papers."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from utils.errors import DataSourceError

ATOM = "http://www.w3.org/2005/Atom"


def _feed(entry_xml: str) -> str:
    return f'<feed xmlns="{ATOM}">{entry_xml}</feed>'


def test_arxiv_error_entry_is_not_a_paper():
    from sources.arxiv import ArxivSource

    feed = _feed(
        "<entry><id>http://arxiv.org/api/errors#incorrect_id_format_for_2401.99999</id>"
        "<title>Error</title><summary>incorrect id format</summary></entry>"
    )
    assert ArxivSource()._parse_feed(feed) == []


def test_arxiv_get_by_id_reports_not_found_for_an_error_entry():
    from sources.arxiv import ArxivSource

    feed = _feed(
        "<entry><id>http://arxiv.org/api/errors#incorrect_id_format_for_2401.99999</id><title>Error</title></entry>"
    )
    source = ArxivSource()
    with patch.object(ArxivSource, "_request", return_value=feed):
        with pytest.raises(DataSourceError, match="not found"):
            source.get_by_id("2401.99999")


def test_arxiv_real_entry_still_parses():
    from sources.arxiv import ArxivSource

    feed = _feed(
        "<entry><id>http://arxiv.org/abs/2401.00001v1</id><title>Real  Title</title>"
        "<summary>S</summary><author><name>A B</name></author></entry>"
    )
    papers = ArxivSource()._parse_feed(feed)
    assert [p["title"] for p in papers] == ["Real Title"]
