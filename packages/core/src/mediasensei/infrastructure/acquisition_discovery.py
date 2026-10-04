from __future__ import annotations

import hashlib
import html
import ipaddress
import json
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast

from mediasensei.domain.acquisition import (
    DiscoveryCandidate,
    DiscoveryPage,
    DiscoveryRequest,
)


class AcquisitionError(RuntimeError):
    pass


class AcquisitionDownloader(Protocol):
    downloader_id: str
    version: str

    def download(self, url: str, destination: Path, *, max_bytes: int) -> DownloadReceipt: ...


@dataclass(frozen=True, slots=True)
class DownloadReceipt:
    final_url: str
    content_type: str
    byte_size: int


class DirectUrlDiscoveryProvider:
    provider_id = "direct-url"
    version = "1.0.0"

    def available(self) -> bool:
        return True

    def capabilities(self) -> dict[str, Any]:
        return {
            "modalities": ["image"],
            "requires_credentials": False,
            "supports_pagination": False,
            "source": "manual URLs",
        }

    def search(self, request: DiscoveryRequest) -> DiscoveryPage:
        urls = [value.strip() for value in re.split(r"[\r\n,]+", request.query) if value.strip()]
        candidates = tuple(
            DiscoveryCandidate(
                provider_id=self.provider_id,
                remote_id=hashlib.sha256(url.encode()).hexdigest(),
                source_url=url,
                title=(Path(urllib.parse.urlsplit(url).path).name or "Direct image URL"),
            )
            for url in urls[: request.limit]
            if urllib.parse.urlsplit(url).scheme in {"http", "https"}
        )
        return DiscoveryPage(candidates)


class OpenverseDiscoveryProvider:
    provider_id = "openverse"
    version = "api-v1"
    endpoint = "https://api.openverse.org/v1/images/"

    def __init__(self, *, opener: urllib.request.OpenerDirector | None = None) -> None:
        self._opener = opener or urllib.request.build_opener()

    def available(self) -> bool:
        return True

    def capabilities(self) -> dict[str, Any]:
        return {
            "modalities": ["image"],
            "requires_credentials": False,
            "supports_pagination": True,
            "source": "Openverse",
            "license_metadata": True,
            "open_licensed_catalog": True,
        }

    def search(self, request: DiscoveryRequest) -> DiscoveryPage:
        started = time.perf_counter()
        page_number = max(1, int(request.cursor or 1))
        params = {
            "q": request.query,
            "page": str(page_number),
            "page_size": str(max(1, min(request.limit, 50))),
            "mature": "false",
        }
        payload = self._request_json(params)
        candidates: list[DiscoveryCandidate] = []
        for item in cast(list[dict[str, Any]], payload.get("results") or []):
            source_url = str(item.get("url") or "")
            if not source_url.startswith("https://"):
                continue
            filetype = str(item.get("filetype") or "").casefold().strip(".")
            mime_type = _image_mime(filetype)
            license_name = (
                " ".join(
                    value
                    for value in (
                        str(item.get("license") or "").upper(),
                        str(item.get("license_version") or ""),
                    )
                    if value
                )
                or None
            )
            candidates.append(
                DiscoveryCandidate(
                    provider_id=self.provider_id,
                    remote_id=str(
                        item.get("id") or hashlib.sha256(source_url.encode()).hexdigest()
                    ),
                    source_url=source_url,
                    landing_page_url=_string_or_none(item.get("foreign_landing_url")),
                    preview_url=_string_or_none(item.get("thumbnail")),
                    title=_string_or_none(item.get("title")),
                    description=_string_or_none(item.get("description")),
                    mime_type=mime_type,
                    width=_int_or_none(item.get("width")),
                    height=_int_or_none(item.get("height")),
                    author=_string_or_none(item.get("creator")),
                    license=license_name,
                    estimated_size=_int_or_none(item.get("filesize")),
                    metadata={
                        "openverse_provider": item.get("provider"),
                        "openverse_source": item.get("source"),
                        "license_url": item.get("license_url"),
                        "attribution": item.get("attribution"),
                    },
                )
            )
        current = int(payload.get("page") or page_number)
        page_count = int(payload.get("page_count") or current)
        next_cursor = str(current + 1) if current < page_count else None
        return DiscoveryPage(
            tuple(candidates),
            next_cursor,
            round((time.perf_counter() - started) * 1000, 3),
        )

    def _request_json(self, params: dict[str, str]) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{self.endpoint}?{urllib.parse.urlencode(params)}",
            headers={
                "User-Agent": "MediaSensei/0.9 (https://github.com/MediaSensei/MediaSensei)",
                "Accept": "application/json",
            },
        )
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                with self._opener.open(request, timeout=30) as response:
                    return cast(dict[str, Any], json.load(response))
            except (OSError, urllib.error.URLError, json.JSONDecodeError) as error:
                last_error = error
                if attempt < 2:
                    time.sleep(0.25 * (2**attempt))
        raise AcquisitionError(f"Openverse discovery failed: {last_error}")


class WikimediaCommonsDiscoveryProvider:
    provider_id = "wikimedia-commons"
    version = "action-api-v1"
    endpoint = "https://commons.wikimedia.org/w/api.php"

    def __init__(self, *, opener: urllib.request.OpenerDirector | None = None) -> None:
        self._opener = opener or urllib.request.build_opener()

    def available(self) -> bool:
        return True

    def capabilities(self) -> dict[str, Any]:
        return {
            "modalities": ["image"],
            "requires_credentials": False,
            "supports_pagination": True,
            "source": "Wikimedia Commons",
            "license_metadata": True,
        }

    def search(self, request: DiscoveryRequest) -> DiscoveryPage:
        started = time.perf_counter()
        offset = int(request.cursor or 0)
        params = {
            "action": "query",
            "format": "json",
            "formatversion": "2",
            "generator": "search",
            "gsrsearch": f"filetype:bitmap {request.query}",
            "gsrnamespace": "6",
            "gsrlimit": str(max(1, min(request.limit, 50))),
            "gsroffset": str(offset),
            "prop": "imageinfo",
            "iiprop": "url|size|mime|extmetadata",
            "iiextmetadatafilter": ("LicenseShortName|UsageTerms|Artist|ImageDescription"),
            "iimetadataversion": "latest",
            "maxlag": "5",
        }
        payload = self._request_json(params)
        pages = cast(dict[str, Any], payload.get("query") or {}).get("pages") or []
        candidates: list[DiscoveryCandidate] = []
        for page in pages:
            info_values = page.get("imageinfo") or []
            if not info_values:
                continue
            info = info_values[0]
            mime = str(info.get("mime") or "")
            source_url = str(info.get("url") or "")
            if not mime.startswith("image/") or not source_url.startswith("https://"):
                continue
            metadata = info.get("extmetadata") or {}
            title = str(page.get("title") or "").removeprefix("File:")
            candidates.append(
                DiscoveryCandidate(
                    provider_id=self.provider_id,
                    remote_id=str(
                        page.get("pageid") or hashlib.sha256(source_url.encode()).hexdigest()
                    ),
                    source_url=source_url,
                    landing_page_url=info.get("descriptionurl"),
                    title=title,
                    description=_metadata_value(metadata, "ImageDescription"),
                    mime_type=mime,
                    width=_int_or_none(info.get("width")),
                    height=_int_or_none(info.get("height")),
                    author=_metadata_value(metadata, "Artist"),
                    license=(
                        _metadata_value(metadata, "LicenseShortName")
                        or _metadata_value(metadata, "UsageTerms")
                    ),
                    estimated_size=_int_or_none(info.get("size")),
                    metadata={"canonical_title": str(page.get("title") or "")},
                )
            )
        continuation = cast(dict[str, Any], payload.get("continue") or {})
        next_cursor = str(continuation["gsroffset"]) if "gsroffset" in continuation else None
        return DiscoveryPage(
            tuple(candidates),
            next_cursor,
            round((time.perf_counter() - started) * 1000, 3),
        )

    def _request_json(self, params: dict[str, str]) -> dict[str, Any]:
        url = f"{self.endpoint}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": ("MediaSensei/0.9 (https://github.com/MediaSensei/MediaSensei)"),
                "Accept": "application/json",
            },
        )
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                with self._opener.open(request, timeout=30) as response:
                    payload = cast(dict[str, Any], json.load(response))
                if cast(dict[str, Any], payload.get("error") or {}).get("code") == "maxlag":
                    raise AcquisitionError("Wikimedia Commons requested backoff")
                return payload
            except (
                OSError,
                urllib.error.URLError,
                json.JSONDecodeError,
                AcquisitionError,
            ) as error:
                last_error = error
                if attempt < 2:
                    time.sleep(0.25 * (2**attempt))
        raise AcquisitionError(f"Wikimedia Commons discovery failed: {last_error}")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        return None


class SafeHttpDownloader:
    downloader_id = "safe-http"
    version = "1.0.0"

    def __init__(self, *, allow_private_network: bool = False, max_redirects: int = 5) -> None:
        self.allow_private_network = allow_private_network
        self.max_redirects = max(0, min(max_redirects, 10))
        self._opener = urllib.request.build_opener(_NoRedirect())

    def download(self, url: str, destination: Path, *, max_bytes: int) -> DownloadReceipt:
        current = canonicalize_url(url)
        for redirect_count in range(self.max_redirects + 1):
            validate_remote_url(
                current,
                allow_private_network=self.allow_private_network,
            )
            request = urllib.request.Request(
                current,
                headers={
                    "User-Agent": ("MediaSensei/0.9 (https://github.com/MediaSensei/MediaSensei)"),
                    "Accept": "image/*",
                },
            )
            try:
                response = self._opener.open(request, timeout=45)
            except urllib.error.HTTPError as error:
                if error.code in {301, 302, 303, 307, 308}:
                    if redirect_count >= self.max_redirects:
                        raise AcquisitionError("Download exceeded the redirect limit") from error
                    location = error.headers.get("Location")
                    if not location:
                        raise AcquisitionError(
                            "Download redirect omitted its destination"
                        ) from error
                    current = canonicalize_url(urllib.parse.urljoin(current, location))
                    continue
                raise AcquisitionError(f"Download failed with HTTP {error.code}") from error
            with response:
                content_type = str(response.headers.get_content_type() or "").casefold()
                if not content_type.startswith("image/"):
                    raise AcquisitionError("Remote content is not an image")
                declared = _int_or_none(response.headers.get("Content-Length"))
                if declared is not None and declared > max_bytes:
                    raise AcquisitionError("Remote image exceeds the per-file byte limit")
                destination.parent.mkdir(parents=True, exist_ok=True)
                written = 0
                with destination.open("wb") as writer:
                    while chunk := response.read(1024 * 1024):
                        written += len(chunk)
                        if written > max_bytes:
                            raise AcquisitionError("Remote image exceeded the per-file byte limit")
                        writer.write(chunk)
                return DownloadReceipt(current, content_type, written)
        raise AcquisitionError("Download redirect handling failed")


def canonicalize_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value.strip())
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Remote URLs must use HTTP or HTTPS and include a hostname")
    if parsed.username or parsed.password:
        raise ValueError("Remote URLs cannot contain embedded credentials")
    scheme = parsed.scheme.casefold()
    hostname = parsed.hostname.casefold().rstrip(".")
    port = parsed.port
    netloc = hostname
    if port is not None and not (
        (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    ):
        netloc = f"{hostname}:{port}"
    path = urllib.parse.quote(
        urllib.parse.unquote(parsed.path or "/"),
        safe="/%:@",
    )
    return urllib.parse.urlunsplit((scheme, netloc, path, parsed.query, ""))


def validate_remote_url(value: str, *, allow_private_network: bool = False) -> str:
    canonical = canonicalize_url(value)
    parsed = urllib.parse.urlsplit(canonical)
    assert parsed.hostname is not None
    if parsed.scheme != "https" and not allow_private_network:
        raise ValueError("Remote acquisition requires HTTPS")
    addresses = {
        ipaddress.ip_address(item[4][0])
        for item in socket.getaddrinfo(
            parsed.hostname,
            parsed.port or (443 if parsed.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    }
    if not addresses:
        raise ValueError("Remote host did not resolve")
    if not allow_private_network and any(
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
        for address in addresses
    ):
        raise ValueError("Remote URL resolves to a blocked local or private address")
    return canonical


def _string_or_none(value: object) -> str | None:
    clean = str(value or "").strip()
    return clean or None


def _image_mime(filetype: str) -> str | None:
    normalized = "jpeg" if filetype in {"jpg", "jpeg"} else filetype
    return (
        f"image/{normalized}"
        if normalized in {"jpeg", "png", "gif", "webp", "tiff", "bmp"}
        else None
    )


def _metadata_value(metadata: dict[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    if isinstance(value, dict):
        value = value.get("value")
    if value is None:
        return None
    clean = re.sub(r"<[^>]+>", " ", html.unescape(str(value)))
    return " ".join(clean.split())[:2000] or None


def _int_or_none(value: Any) -> int | None:
    return int(value) if value not in {None, ""} else None
