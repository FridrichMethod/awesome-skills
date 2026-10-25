"""Regression tests for the stand-alone converter scripts (no network access)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def _load(name: str, filename: str):
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


converters = _load("nature_search_converters", "converters.py")
format_converter = _load("nature_search_format_converter", "format-converter.py")


def test_format_converter_imports_urlopen_for_real_downloads():
    response = MagicMock()
    response.__enter__.return_value.read.return_value = b"PMID- 1\n"
    with patch.object(format_converter, "urlopen", return_value=response) as opened:
        assert format_converter.efetch_medline("1") == "PMID- 1\n"
    opened.assert_called_once()


def test_ris_escape_keeps_comparison_operators():
    assert converters.ris_escape("Effect at p<0.05 and p>0.01") == "Effect at p<0.05 and p>0.01"


def test_ris_escape_still_strips_markup():
    assert converters.ris_escape("Role of <i>E. coli</i> in <b>disease</b>") == "Role of E. coli in disease"
    assert converters.ris_escape("line<br/>break") == "line break"


def test_medline_bibtex_authors_are_surname_comma_initials():
    fields = {"PMID": ["1"], "AU": ["Smith J", "Doe AB", "Van Der Berg JJ"], "TI": ["T"]}
    bib = converters.medline_to_bib(fields)
    assert "author  = { Smith, J and Doe, AB and Van Der Berg, JJ }" in bib


def test_medline_bibtex_leaves_collective_names_alone():
    bib = converters.medline_to_bib({"PMID": ["1"], "AU": ["World Health Organization"], "TI": ["T"]})
    assert "author  = { World Health Organization }" in bib


def test_zero_retries_still_makes_one_attempt(tmp_path):
    import json

    payload = {"message": {"title": ["A Title"], "author": [{"family": "Smith", "given": "J"}], "issued": {"date-parts": [[2020]]}}}
    response = MagicMock()
    response.__enter__.return_value.read.return_value = json.dumps(payload).encode()
    with patch.object(format_converter, "urlopen", return_value=response), patch.object(format_converter, "DELAY", 0):
        ok, name = format_converter.download_crossref("10.1/x", str(tmp_path), "ris", retries=0)
    assert ok, name
    assert (tmp_path / name).exists()


def test_zero_retries_reports_failure_instead_of_crashing(tmp_path):
    with patch.object(format_converter, "urlopen", side_effect=OSError("boom")), patch.object(format_converter, "DELAY", 0):
        ok, message = format_converter.download_crossref("10.1/x", str(tmp_path), "ris", retries=0)
    assert not ok
    assert "boom" in message
