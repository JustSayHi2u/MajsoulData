#!/usr/bin/env python3
"""Audit every resource family exposed by MajsoulMax against the live client."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from get_max_data import (  # noqa: E402
    CLIENT_TIMEZONE,
    has_expired_name,
    is_past_item_expiry,
    item_ids_with_local_assets,
    title_ids_with_local_assets,
)
from src.pipeline import (  # noqa: E402
    DEFAULT_CLIENT_URL,
    DEFAULT_TEXTURE_PROFILES,
    default_client_settings_url,
    fetch_bytes,
    fetch_json,
    fetch_text,
    join_url,
    make_session,
    parse_bundle_info,
    parse_client_html,
    resolve_bundle_base_url,
    resolve_texture_profile,
    resolve_warehouse_url,
)


DATA = ROOT / "data"
LOCALIZED_VARIANTS = {"common", "chs", "chs_t", "jp", "en", "kr"}


def read_json(relative_path: str):
    return json.loads((DATA / relative_path).read_text(encoding="utf-8"))


def normalize(path: str) -> str:
    return path.replace("\\", "/").strip("/").lower()


def canonical_bundle_path(path: str) -> str:
    parts = normalize(path).split("/")
    if parts and parts[0] == "myassets":
        parts = parts[1:]
    return "/".join(part for part in parts if part not in LOCALIZED_VARIANTS)


def live_asset_paths(timeout: int) -> tuple[dict, set[str]]:
    metadata = read_json("meta.json")
    session = make_session()
    client_url = metadata.get("client_url") or DEFAULT_CLIENT_URL
    client = parse_client_html(fetch_text(session, client_url, timeout))
    settings = fetch_json(
        session,
        default_client_settings_url(client_url, client.get("issuer")),
        timeout,
    )
    warehouse = fetch_json(session, resolve_warehouse_url(settings), timeout)
    profile, profile_base, bundle_hash = resolve_texture_profile(
        session,
        resolve_bundle_base_url(warehouse),
        DEFAULT_TEXTURE_PROFILES,
        timeout,
    )
    _, asset_infos = parse_bundle_info(
        fetch_bytes(session, join_url(profile_base, "bundle_info_so.majset"), timeout)
    )
    live = {
        "issuer": client.get("issuer"),
        "product_version": client.get("product_version"),
        "bundle_profile": profile,
        "bundle_hash": bundle_hash,
    }
    for key in ("issuer", "product_version", "bundle_profile", "bundle_hash"):
        if live[key] != metadata.get(key):
            raise RuntimeError(
                f"live {key}={live[key]!r} does not match data/meta.json "
                f"value {metadata.get(key)!r}"
            )
    return live, {
        normalize(asset["assetPath"])
        for asset in asset_infos
        if isinstance(asset, dict) and isinstance(asset.get("assetPath"), str)
    }


def audit(timeout: int) -> dict:
    live, bundle_paths = live_asset_paths(timeout)
    canonical_paths = {canonical_bundle_path(path) for path in bundle_paths}
    metadata = read_json("meta.json")
    issuer = metadata["issuer"]
    localized = read_json(f"client/docs/localizedImg_{issuer}.json")
    localized_paths = {
        normalize(item["filepath"])
        for item in localized.get("items", [])
        if isinstance(item, dict) and isinstance(item.get("filepath"), str)
    }
    actual_localized_paths = localized_paths & canonical_paths

    items = read_json("tables/item_definition/item.json")
    views = {
        row["id"]: row for row in read_json("tables/item_definition/view.json")
    }
    titles = read_json("tables/item_definition/title.json")
    characters = read_json("tables/item_definition/character.json")
    skins = read_json("tables/item_definition/skin.json")
    loading_rows = read_json("tables/item_definition/loading_image.json")
    bgm_rows = read_json("tables/audio/bgm.json")
    voice_rows = read_json("tables/voice/sound.json")

    now = datetime.now(CLIENT_TIMEZONE)
    usable_item_ids = set(item_ids_with_local_assets(items, localized, now=now))
    usable_items = [item for item in items if item.get("id") in usable_item_ids]
    usable_title_ids = set(title_ids_with_local_assets(titles, localized))

    failures: dict[str, list] = {}
    failures["decoration_icons"] = [
        item["id"]
        for item in usable_items
        if normalize(item["icon"]) not in actual_localized_paths
    ]
    runtime_failures = []
    for item in usable_items:
        if item.get("type") in (4, 5, 9):
            continue
        resource_name = (views.get(item["id"]) or {}).get("res_name")
        if resource_name and not any(
            f"/{str(resource_name).lower()}/" in f"/{path}/"
            for path in bundle_paths
        ):
            runtime_failures.append(item["id"])
    failures["decoration_runtime"] = runtime_failures

    failures["titles"] = [
        title["id"]
        for title in titles
        if title["id"] in usable_title_ids
        and normalize(title["icon"]) not in actual_localized_paths
    ]

    skin_ids = {skin["id"] for skin in skins}
    failures["character_skin_references"] = [
        character["id"]
        for character in characters
        if character.get("init_skin") not in skin_ids
        or character.get("full_fetter_skin") not in skin_ids
    ]
    failures["skin_bundles"] = [
        skin["id"]
        for skin in skins
        if not any(
            path.startswith(f"myassets/{normalize(skin['path'])}/")
            for path in bundle_paths
        )
    ]

    loading_item_rows = [item for item in items if item.get("category") == 8]
    failures["loading_item_icons"] = [
        item["id"]
        for item in loading_item_rows
        if not isinstance(item.get("icon"), str)
        or normalize(item["icon"]) not in actual_localized_paths
    ]
    failures["loading_images"] = [
        row["id"]
        for row in loading_rows
        if normalize(row["img_path"]) not in actual_localized_paths
        or normalize(row["thumb_path"]) not in actual_localized_paths
    ]

    bgm_by_id = {row["id"]: row for row in bgm_rows}
    music_failures = []
    for item in usable_items:
        if item.get("type") == 4:
            paths = item.get("sargs") or []
            if len(paths) != 1 or not str(paths[0]).lower().endswith(".mp3"):
                music_failures.append(item["id"])
        elif item.get("type") == 9:
            row = bgm_by_id.get(item["id"])
            if not row or not str(row.get("path", "")).lower().endswith(".mp3"):
                music_failures.append(item["id"])
    failures["music_references"] = music_failures

    voice_ids = {row.get("id") for row in voice_rows if row.get("path")}
    failures["character_voice_references"] = [
        character["id"]
        for character in characters
        if character.get("sound") not in voice_ids
    ]

    expired_placeholders = [
        item["id"]
        for item in items
        if item.get("category") == 5 and has_expired_name(item)
    ]
    expired_by_time = [
        item["id"]
        for item in items
        if item.get("category") == 5 and is_past_item_expiry(item, now)
    ]
    missing_issuer_icons = [
        item["id"]
        for item in items
        if item.get("category") == 5
        and (
            not isinstance(item.get("icon"), str)
            or normalize(item["icon"]) not in localized_paths
        )
    ]

    return {
        "live": live,
        "counts": {
            "bundle_assets": len(bundle_paths),
            "characters": len(characters),
            "skins": len(skins),
            "titles_source": len(titles),
            "titles_usable": len(usable_title_ids),
            "decorations_source": sum(item.get("category") == 5 for item in items),
            "decorations_usable": len(usable_item_ids),
            "loading_images": len(
                {row["id"] for row in loading_rows}
                | {item["id"] for item in loading_item_rows}
            ),
            "music": len(bgm_rows)
            + sum(item.get("type") == 4 for item in usable_items),
            "voice_rows": len(voice_rows),
        },
        "excluded": {
            "expired_placeholder": expired_placeholders,
            "expired_time": expired_by_time,
            "missing_current_issuer_icon": missing_issuer_icons,
        },
        "failures": {key: value for key, value in failures.items() if value},
        "decoration_types": dict(
            sorted(Counter(str(item.get("type")) for item in usable_items).items())
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = audit(args.timeout)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(
            "Official resource audit: "
            f"Unity={report['live']['product_version']} "
            f"Bundle={report['live']['bundle_hash']}"
        )
        for key, value in report["counts"].items():
            print(f"  {key}: {value}")
        for key, values in report["excluded"].items():
            print(f"  excluded {key}: {len(values)}")
        print(f"  failures: {report['failures'] or 'none'}")
    return 1 if report["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
