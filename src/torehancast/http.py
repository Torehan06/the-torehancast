"""A small, polite HTTP client shared by all adapters.

Identifies itself honestly, sends conditional requests so unchanged files cost the
state's servers almost nothing, and never tries to get around bot challenges:
a challenge page is reported as an error, not worked around.
"""

from __future__ import annotations

import httpx

USER_AGENT = "torehancast/0.1 (election-night research project; contact: see README)"

# Markers of interstitial bot-challenge pages. Seeing one means "this feed is
# unavailable to us", never "try harder".
_CHALLENGE_MARKERS = ("cf-chl", "Just a moment...", "challenge-platform/h/")


class FeedUnavailable(RuntimeError):
    pass


class PoliteClient:
    def __init__(self, timeout: float = 30.0):
        self._client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        )
        self._etags: dict[str, str] = {}
        self._cache: dict[str, bytes] = {}

    def get(self, url: str, **kwargs) -> bytes:
        headers = {}
        if url in self._etags:
            headers["If-None-Match"] = self._etags[url]
        r = self._client.get(url, headers=headers, **kwargs)
        if r.status_code == 304:
            return self._cache[url]
        if r.status_code in (403, 503) and any(m in r.text for m in _CHALLENGE_MARKERS):
            raise FeedUnavailable(f"{url}: bot challenge page (not bypassing)")
        if r.status_code == 204:
            raise FeedUnavailable(f"{url}: 204 No Content (election not published yet?)")
        r.raise_for_status()
        if etag := r.headers.get("ETag"):
            self._etags[url] = etag
            self._cache[url] = r.content
        return r.content

    def post(self, url: str, data: dict) -> bytes:
        r = self._client.post(url, data=data)
        r.raise_for_status()
        return r.content

    def close(self) -> None:
        self._client.close()
