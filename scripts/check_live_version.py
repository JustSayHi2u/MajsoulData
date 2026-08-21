#!/usr/bin/env python3
"""Cheap live-version preflight for the frequent scheduled update monitor."""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def fetch_text(url: str, timeout: int = 15) -> str:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            request = Request(url, headers={"User-Agent": USER_AGENT})
            with urlopen(request, timeout=timeout) as response:
                return response.read().decode(response.headers.get_content_charset() or "utf-8")
        except Exception as error:
            last_error = error
            if attempt < 2:
                time.sleep(1 << attempt)
    raise RuntimeError(f"failed to fetch {url}: {last_error}") from last_error


def fetch_json(url: str, timeout: int = 15) -> dict:
    return json.loads(fetch_text(url, timeout))


def choose_url(entries: list[dict]) -> str:
    if not entries:
        raise ValueError("URL list is empty")
    selected = max(
        entries,
        key=lambda item: (item.get("Priority", 0), item.get("weight", 0)),
    )
    if not selected.get("url"):
        raise ValueError("selected URL entry has no url")
    return selected["url"]


def live_metadata(
    metadata: dict,
    *,
    text_loader: Callable[[str, int], str] = fetch_text,
    json_loader: Callable[[str, int], dict] = fetch_json,
    timeout: int = 15,
) -> dict[str, str]:
    client_url = metadata["client_url"]
    html = text_loader(client_url, timeout)
    product_match = re.search(
        r"productVersion\s*:\s*['\"]([^'\"]+)['\"]",
        html,
    )
    if product_match is None:
        raise ValueError("productVersion is missing from the client page")

    parsed = urlsplit(client_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    issuer = metadata["issuer"]
    client_settings_url = (
        f"{origin}/assetbundles/clientBundleSettings/{issuer}-release.json"
    )
    client_settings = json_loader(client_settings_url, timeout)
    warehouses = client_settings.get("warehouses") or []
    if not warehouses:
        raise ValueError("clientBundleSettings has no warehouses")
    warehouse = warehouses[0]
    warehouse_url = urljoin(
        choose_url(warehouse.get("urls") or []).rstrip("/") + "/",
        str(warehouse["warehouseSettingPath"]).lstrip("/"),
    )
    warehouse_settings = json_loader(warehouse_url, timeout)
    bundle_root = urljoin(
        choose_url(warehouse_settings.get("urls") or []).rstrip("/") + "/",
        str(warehouse_settings["bundlePath"]).lstrip("/"),
    ).rstrip("/")
    bundle_hash = text_loader(
        f"{bundle_root}/{metadata['bundle_profile']}/bundle_hash.txt",
        timeout,
    ).strip()
    if not re.fullmatch(r"[0-9a-f]{40}", bundle_hash):
        raise ValueError(f"invalid live bundle hash: {bundle_hash!r}")
    return {
        "product_version": product_match.group(1),
        "bundle_hash": bundle_hash,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metadata", type=Path, default=ROOT / "data/meta.json")
    args = parser.parse_args()
    installed = json.loads(args.metadata.read_text(encoding="utf-8"))
    live = live_metadata(installed)
    changed = any(
        installed.get(key) != live.get(key)
        for key in ("product_version", "bundle_hash")
    )
    print(
        "Live resource preflight: "
        f"installed={installed.get('product_version')}/{installed.get('bundle_hash')} "
        f"live={live['product_version']}/{live['bundle_hash']} changed={str(changed).lower()}"
    )
    output = os.getenv("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as file:
            file.write(f"changed={str(changed).lower()}\n")
            file.write(f"product_version={live['product_version']}\n")
            file.write(f"bundle_hash={live['bundle_hash']}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
