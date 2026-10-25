"""PubMed article parsing edge cases (no network access)."""

from __future__ import annotations

import defusedxml.ElementTree as ET

from sources.pubmed import _parse_article


def _article(title_xml: str) -> object:
    return ET.fromstring(
        f"""<PubmedArticle><MedlineCitation><PMID>1</PMID><Article>
        <ArticleTitle>{title_xml}</ArticleTitle>
        <Journal><Title>J Test</Title><JournalIssue><PubDate><Year>2020</Year></PubDate></JournalIssue></Journal>
        </Article></MedlineCitation></PubmedArticle>"""
    )


def test_title_with_inline_markup_is_not_truncated():
    parsed = _parse_article(_article("Role of <i>Escherichia coli</i> in disease."))
    assert parsed["title"] == "Role of Escherichia coli in disease."


def test_plain_title_is_unchanged():
    assert _parse_article(_article("Genomic Analysis of Cancer"))["title"] == "Genomic Analysis of Cancer"
