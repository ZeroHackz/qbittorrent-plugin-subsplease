# VERSION: 1.00
# AUTHORS: ZeroHackz (https://github.com/ZeroHackz)
#
# MIT License
#
# Copyright (c) 2026 ZeroHackz
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""SubsPlease search engine plugin for qBittorrent.

SubsPlease publishes every release in 480p, 720p and 1080p. This plugin only
reports the 1080p release of each episode, so the result list never needs
manual resolution filtering.

Searching with an empty query (or with the token ``!latest``) returns the
site's current "Latest Releases" instead of running a search. Prepending
``!all`` to a query disables the 1080p filter for that one search.
"""

from __future__ import annotations

import json
import sys
import urllib.parse
from datetime import timezone
from email.utils import parsedate_to_datetime
from typing import Any, Iterator, Optional

from helpers import retrieve_url
from novaprinter import prettyPrinter


class subsplease:
    """qBittorrent search plugin for https://subsplease.org."""

    url = "https://subsplease.org"
    name = "SubsPlease"
    # SubsPlease is an anime release group; "tv" is accepted as an alias so a
    # search started from the TV category still returns results.
    supported_categories = {"all": "0", "anime": "0", "tv": "0"}

    api_url = "https://subsplease.org/api/"
    # The API needs *some* timezone to render result dates; dates are converted
    # to Unix timestamps below, so the value itself does not matter.
    timezone = "UTC"
    # Only releases whose resolution starts with this are reported.
    resolution = "1080"

    # ------------------------------------------------------------------ search

    def search(self, what: str, cat: str = "all") -> None:
        """Run a query and print one ``prettyPrinter`` line per 1080p release."""
        query, include_everything = self._parse_query(what)

        payload = self._fetch(query)
        if payload is None:
            return

        results = []
        seen_links = set()
        for row in self._iter_results(payload, include_everything):
            if row["link"] in seen_links:
                continue
            seen_links.add(row["link"])
            results.append(row)

        # Newest first: the API has no seed/leech data to sort on.
        results.sort(key=lambda row: (row["pub_date"], row["name"]), reverse=True)

        for row in results:
            prettyPrinter(row)

    @staticmethod
    def _parse_query(what: str) -> tuple[str, bool]:
        """Return ``(query, include_everything)`` from qBittorrent's escaped input."""
        tokens = urllib.parse.unquote_plus(what).split()

        include_everything = False
        if tokens and tokens[0].lower() in ("!all", "!any"):
            include_everything = True
            tokens.pop(0)

        if not tokens or tokens[0].lower() in ("!latest", "!new"):
            tokens = []

        return " ".join(tokens), include_everything

    def _fetch(self, query: str) -> Optional[dict[str, Any]]:
        """Call the SubsPlease API and return the decoded JSON object."""
        if query:
            params = {"f": "search", "s": query, "tz": self.timezone}
        else:
            params = {"f": "latest", "tz": self.timezone}

        api_request = f"{self.api_url}?{urllib.parse.urlencode(params)}"

        try:
            body = self._retrieve(api_request)
        except Exception as exc:  # noqa: BLE001 - never let a plugin kill the search
            self._warn(f"request failed: {exc}")
            return None

        if not body.strip():
            self._warn("subsplease.org returned an empty response")
            return None

        try:
            payload = json.loads(body)
        except ValueError:
            self._warn("could not parse the API response (site changed or request blocked)")
            return None

        # SubsPlease answers "nothing found" with an empty JSON list.
        if payload == []:
            return {}
        if not isinstance(payload, dict):
            self._warn("unexpected API response")
            return None

        return payload

    @staticmethod
    def _retrieve(api_request: str) -> str:
        try:
            return retrieve_url(api_request, unescape_html_entities=False)
        except TypeError:
            # qBittorrent < 5.2 ships a helpers.py without that parameter.
            return retrieve_url(api_request)

    # ------------------------------------------------------------------ parsing

    def _iter_results(
        self, payload: dict[str, Any], include_everything: bool
    ) -> Iterator[dict[str, Any]]:
        """Yield one result dictionary per matching release download."""
        for release in payload.values():
            if not isinstance(release, dict):
                continue

            show = str(release.get("show") or "").strip()
            episode = str(release.get("episode") or "").strip()
            page = str(release.get("page") or "").strip()
            pub_date = self._to_timestamp(release.get("release_date"))

            downloads = release.get("downloads")
            if not isinstance(downloads, list):
                continue

            for download in downloads:
                if not isinstance(download, dict):
                    continue

                resolution = str(download.get("res") or "").strip()
                if not include_everything and not resolution.lower().startswith(self.resolution):
                    continue

                magnet = str(download.get("magnet") or "").strip()
                if not magnet.lower().startswith("magnet:"):
                    continue

                name, size = self._parse_magnet(magnet)

                yield {
                    "link": magnet,
                    "name": name or self._fallback_name(show, episode, resolution),
                    "size": size,
                    "seeds": -1,
                    "leech": -1,
                    "engine_url": self.url,
                    "desc_link": self._show_url(page),
                    "pub_date": pub_date,
                }

    def _show_url(self, page: str) -> str:
        if page:
            return f"{self.url}/shows/{urllib.parse.quote(page)}/"
        return f"{self.url}/shows/"

    def _fallback_name(self, show: str, episode: str, resolution: str) -> str:
        title = " - ".join(part for part in (show, episode) if part)
        suffix = f"{resolution}p" if resolution else "unknown"
        return f"[SubsPlease] {title or 'release'} ({suffix})"

    @staticmethod
    def _parse_magnet(magnet: str) -> tuple[str, int]:
        """Return ``(display name, size in bytes)`` from a magnet link."""
        _, _, query = magnet.partition("?")
        params: dict[str, str] = {}

        for chunk in query.split("&"):
            key, separator, value = chunk.partition("=")
            if separator:
                params.setdefault(key.lower(), urllib.parse.unquote(value))

        name = params.get("dn", "").strip()

        try:
            size = int(params["xl"])
        except (KeyError, ValueError):
            size = -1

        return name, size

    @staticmethod
    def _to_timestamp(value: Any) -> int:
        """Convert an RFC 2822 date such as ``Sun, 08 Nov 2026 16:22:54 +0100``."""
        if not value:
            return -1

        try:
            parsed = parsedate_to_datetime(str(value))
        except (TypeError, ValueError, OverflowError):
            return -1

        if parsed is None:
            return -1
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)

        return int(parsed.timestamp())

    @staticmethod
    def _warn(message: str) -> None:
        """Plugins may only write results to stdout, so diagnostics go to stderr."""
        print(f"SubsPlease: {message}", file=sys.stderr)
