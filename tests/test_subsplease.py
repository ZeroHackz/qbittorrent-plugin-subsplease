"""Offline unit tests for the SubsPlease qBittorrent search plugin.

The plugin imports ``helpers`` and ``novaprinter`` from qBittorrent's nova3
runtime, so small stand-ins are registered before the module is loaded. The
tests never touch the network: API responses come from ``fixtures/``.

Run with: python -m unittest discover -s tests -v
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT_DIR = Path(__file__).resolve().parent.parent
FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "search_frieren.json"


def _install_qbittorrent_stubs() -> None:
    """Provide the two modules that only exist inside qBittorrent's nova3."""
    if "helpers" not in sys.modules:
        helpers = types.ModuleType("helpers")
        helpers.retrieve_url = lambda *args, **kwargs: ""
        sys.modules["helpers"] = helpers

    if "novaprinter" not in sys.modules:
        novaprinter = types.ModuleType("novaprinter")
        novaprinter.prettyPrinter = lambda row: None
        sys.modules["novaprinter"] = novaprinter


_install_qbittorrent_stubs()

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import subsplease  # noqa: E402  (import must follow the stubs)

plugin = subsplease.subsplease


def load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


class MetadataTest(unittest.TestCase):
    def test_required_attributes(self) -> None:
        engine = plugin()
        self.assertEqual(engine.name, "SubsPlease")
        self.assertEqual(engine.url, "https://subsplease.org")
        self.assertIn("all", engine.supported_categories)
        self.assertIn("anime", engine.supported_categories)


class QueryParsingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = plugin()

    def test_plain_query_is_unescaped(self) -> None:
        self.assertEqual(self.engine._parse_query("sousou%20no%20frieren"), ("sousou no frieren", False))

    def test_plus_is_treated_as_space(self) -> None:
        self.assertEqual(self.engine._parse_query("one+piece"), ("one piece", False))

    def test_empty_query_means_latest(self) -> None:
        self.assertEqual(self.engine._parse_query(""), ("", False))
        self.assertEqual(self.engine._parse_query("   "), ("", False))

    def test_latest_tokens(self) -> None:
        self.assertEqual(self.engine._parse_query("!latest"), ("", False))
        self.assertEqual(self.engine._parse_query("!new"), ("", False))

    def test_all_token_disables_resolution_filter(self) -> None:
        self.assertEqual(self.engine._parse_query("!all%20one%20piece"), ("one piece", True))
        self.assertEqual(self.engine._parse_query("!ALL"), ("", True))


class MagnetParsingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = plugin()

    def test_name_and_size(self) -> None:
        magnet = "magnet:?xt=urn:btih:ABC&dn=%5BSubsPlease%5D%20Show%20-%2001%20%281080p%29&xl=12345"
        self.assertEqual(
            self.engine._parse_magnet(magnet),
            ("[SubsPlease] Show - 01 (1080p)", 12345),
        )

    def test_plus_is_not_decoded_as_space(self) -> None:
        magnet = "magnet:?xt=urn:btih:ABC&dn=A%2BB&xl=1"
        self.assertEqual(self.engine._parse_magnet(magnet)[0], "A+B")

    def test_missing_size_becomes_minus_one(self) -> None:
        magnet = "magnet:?xt=urn:btih:ABC&dn=Show"
        self.assertEqual(self.engine._parse_magnet(magnet)[1], -1)

    def test_missing_name_returns_empty_string(self) -> None:
        self.assertEqual(self.engine._parse_magnet("magnet:?xt=urn:btih:ABC&xl=5"), ("", 5))


class TimestampTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = plugin()

    def test_rfc2822_date_with_offset(self) -> None:
        self.assertEqual(self.engine._to_timestamp("Fri, 27 Mar 2026 16:02:39 +0100"), 1774623759)

    def test_missing_or_invalid_dates(self) -> None:
        self.assertEqual(self.engine._to_timestamp(None), -1)
        self.assertEqual(self.engine._to_timestamp(""), -1)
        self.assertEqual(self.engine._to_timestamp("not a date"), -1)


class ResultParsingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = plugin()
        self.payload = load_fixture()

    def _collect(self, include_everything: bool = False, payload: dict | None = None) -> list[dict]:
        return list(self.engine._iter_results(self.payload if payload is None else payload, include_everything))

    def test_only_1080p_is_reported(self) -> None:
        rows = self._collect()
        expected = sum(
            1
            for release in self.payload.values()
            for download in release["downloads"]
            if download["res"].startswith("1080")
        )
        self.assertEqual(len(rows), expected)
        for row in rows:
            self.assertIn("(1080p)", row["name"])
            self.assertNotIn("(720p)", row["name"])
            self.assertNotIn("(480p)", row["name"])

    def test_all_resolutions_when_requested(self) -> None:
        rows = self._collect(include_everything=True)
        expected = sum(len(release["downloads"]) for release in self.payload.values())
        self.assertEqual(len(rows), expected)

    def test_result_fields(self) -> None:
        for row in self._collect():
            self.assertTrue(row["link"].startswith("magnet:?"))
            self.assertTrue(row["name"].startswith("[SubsPlease]"))
            self.assertGreater(row["size"], 0)
            self.assertEqual(row["seeds"], -1)
            self.assertEqual(row["leech"], -1)
            self.assertEqual(row["engine_url"], "https://subsplease.org")
            self.assertRegex(row["desc_link"], r"^https://subsplease\.org/shows/[a-z0-9-]+/$")
            self.assertIsInstance(row["pub_date"], int)
            self.assertGreater(row["pub_date"], 0)

    def test_malformed_releases_are_skipped(self) -> None:
        payload = {
            "good": {
                "show": "Show",
                "episode": "01",
                "page": "show",
                "release_date": "Sun, 08 Nov 2026 16:22:54 +0100",
                "downloads": [{"res": "1080", "magnet": "magnet:?xt=urn:btih:ABC&dn=Good&xl=10"}],
            },
            "not-a-release": "oops",
            "no-downloads": {"show": "Show", "downloads": None},
            "bad-downloads": {
                "show": "Show",
                "downloads": [None, {}, {"res": "1080", "magnet": "https://example.com/file.torrent"}],
            },
        }
        rows = self._collect(payload=payload)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "Good")

    def test_fallback_name_when_magnet_has_no_display_name(self) -> None:
        payload = {
            "release": {
                "show": "Some Show",
                "episode": "07",
                "page": "some-show",
                "downloads": [{"res": "1080", "magnet": "magnet:?xt=urn:btih:ABC&xl=10"}],
            }
        }
        rows = self._collect(payload=payload)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "[SubsPlease] Some Show - 07 (1080p)")


class SearchTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = plugin()
        self.payload = load_fixture()

    def _search(self, query: str, payload: dict | None = None) -> list[dict]:
        rows: list[dict] = []
        with (
            mock.patch.object(subsplease, "prettyPrinter", rows.append),
            mock.patch.object(self.engine, "_fetch", return_value=self.payload if payload is None else payload),
        ):
            self.engine.search(query)
        return rows

    def test_results_are_newest_first(self) -> None:
        dates = [row["pub_date"] for row in self._search("frieren")]
        self.assertEqual(dates, sorted(dates, reverse=True))

    def test_duplicate_releases_are_printed_once(self) -> None:
        payload = load_fixture()
        first_key = next(iter(payload))
        payload[f"{first_key} (duplicate)"] = json.loads(json.dumps(payload[first_key]))

        links = [row["link"] for row in self._search("frieren", payload)]
        self.assertEqual(len(links), len(set(links)))

    def test_failed_request_prints_nothing(self) -> None:
        rows: list[dict] = []
        with (
            mock.patch.object(subsplease, "prettyPrinter", rows.append),
            mock.patch.object(self.engine, "_fetch", return_value=None),
        ):
            self.engine.search("frieren")
        self.assertEqual(rows, [])

    def test_empty_response_is_not_an_error(self) -> None:
        rows: list[dict] = []
        stderr = io.StringIO()
        with (
            mock.patch.object(subsplease, "retrieve_url", lambda *args, **kwargs: "[]"),
            mock.patch.object(subsplease, "prettyPrinter", rows.append),
            contextlib.redirect_stderr(stderr),
        ):
            self.engine.search("zzzzz")
        self.assertEqual(rows, [])
        self.assertEqual(stderr.getvalue(), "")

    def test_end_to_end_with_fixture(self) -> None:
        body = FIXTURE_PATH.read_text(encoding="utf-8")
        rows: list[dict] = []
        with (
            mock.patch.object(subsplease, "retrieve_url", lambda *args, **kwargs: body),
            mock.patch.object(subsplease, "prettyPrinter", rows.append),
        ):
            self.engine.search("frieren")
        self.assertTrue(rows)


class ApiRequestTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = plugin()

    def _request_url(self, query: str) -> str:
        urls: list[str] = []

        def fake_retrieve(url: str, **kwargs: object) -> str:
            urls.append(url)
            return "{}"

        with mock.patch.object(subsplease, "retrieve_url", fake_retrieve):
            self.engine.search(query)

        self.assertEqual(len(urls), 1)
        return urls[0]

    def test_search_request(self) -> None:
        url = self._request_url("sousou%20no%20frieren")
        self.assertIn("f=search", url)
        self.assertIn("s=sousou+no+frieren", url)
        self.assertIn("tz=UTC", url)

    def test_empty_query_uses_latest_endpoint(self) -> None:
        url = self._request_url("")
        self.assertIn("f=latest", url)
        self.assertNotIn("s=", url)


if __name__ == "__main__":
    unittest.main()
