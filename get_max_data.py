import argparse
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ruamel.yaml import YAML


DATA_DIR = Path("data")
# 国服资源表使用固定 UTC+8 时间；避免 Windows Python 缺少 IANA tzdata。
CLIENT_TIMEZONE = timezone(timedelta(hours=8), name="Asia/Shanghai")
EXPIRED_NAME_MARKERS = (
    "已过期",
    "已過期",
    "expired",
    "期限切れ",
    "만료",
)


def _normalized_asset_path(path: str) -> str:
    return path.replace("\\", "/").lstrip("/").lower()


def ids_with_local_assets(records: list[dict], localized_images: dict) -> list[int]:
    """Return record IDs whose icon is shipped by the current client issuer."""
    items = localized_images.get("items")
    if not isinstance(items, list):
        raise ValueError("localizedImg is missing items")
    asset_paths = {
        _normalized_asset_path(item["filepath"])
        for item in items
        if isinstance(item, dict) and isinstance(item.get("filepath"), str)
    }
    record_ids = [
        record["id"]
        for record in records
        if isinstance(record, dict)
        and isinstance(record.get("id"), int)
        and not isinstance(record.get("id"), bool)
        and isinstance(record.get("icon"), str)
        and _normalized_asset_path(record["icon"]) in asset_paths
    ]
    if not record_ids:
        raise ValueError("current issuer has no usable record icons")
    return record_ids


def title_ids_with_local_assets(titles: list[dict], localized_images: dict) -> list[int]:
    """Return title IDs whose icon is shipped by the current client issuer."""
    return ids_with_local_assets(titles, localized_images)


def has_expired_name(record: dict) -> bool:
    """Detect official tombstones that remain in tables after a feature is retired."""
    names = record.get("name")
    if not isinstance(names, dict):
        return False
    return any(
        marker in str(value).lower()
        for value in names.values()
        for marker in EXPIRED_NAME_MARKERS
    )


def parse_client_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=CLIENT_TIMEZONE)
    return parsed.astimezone(CLIENT_TIMEZONE)


def is_past_item_expiry(item: dict, now: datetime | None = None) -> bool:
    value = item.get("item_expire")
    if not isinstance(value, str) or not value.strip():
        return False
    reference = now or datetime.now(CLIENT_TIMEZONE)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=CLIENT_TIMEZONE)
    return parse_client_datetime(value) <= reference.astimezone(CLIENT_TIMEZONE)


def deduplicate_head_frames(items: list[dict]) -> list[dict]:
    """Keep one deterministic item for each visually identical portrait frame."""
    preferred: dict[str, dict] = {}
    for item in items:
        if item.get("type") != 5 or not isinstance(item.get("icon"), str):
            continue
        icon = _normalized_asset_path(item["icon"])
        current = preferred.get(icon)
        rank = (
            item.get("item_expire") is None,
            item.get("item_expire") or "",
            item["id"],
        )
        if current is None:
            preferred[icon] = item
            continue
        current_rank = (
            current.get("item_expire") is None,
            current.get("item_expire") or "",
            current["id"],
        )
        if rank > current_rank:
            preferred[icon] = item

    preferred_ids = {item["id"] for item in preferred.values()}
    return [
        item
        for item in items
        if item.get("type") != 5 or item.get("id") in preferred_ids
    ]


def item_ids_with_local_assets(
    items: list[dict],
    localized_images: dict,
    *,
    now: datetime | None = None,
) -> list[int]:
    """Drop unusable assets and duplicate tournament portrait-frame revisions."""
    decorations = [
        item
        for item in items
        if item.get("category") == 5
        and not has_expired_name(item)
        and not is_past_item_expiry(item, now)
    ]
    decorations = deduplicate_head_frames(decorations)
    return ids_with_local_assets(decorations, localized_images)


def select_character_skin_resources(
    characters: list[dict],
    skins: list[dict],
    bundle_paths: set[str],
) -> dict:
    """Select only characters and skins backed by the current issuer bundle."""
    normalized_bundle_paths = {
        _normalized_asset_path(path) for path in bundle_paths if isinstance(path, str)
    }
    skin_ids_with_bundle = []
    missing_bundle = []
    for skin in skins:
        skin_id = skin.get("id") if isinstance(skin, dict) else None
        skin_path = skin.get("path") if isinstance(skin, dict) else None
        if not isinstance(skin_id, int) or isinstance(skin_id, bool):
            continue
        prefix = (
            f"myassets/{_normalized_asset_path(skin_path).strip('/')}/"
            if isinstance(skin_path, str) and skin_path.strip()
            else ""
        )
        if prefix and any(path.startswith(prefix) for path in normalized_bundle_paths):
            skin_ids_with_bundle.append(skin_id)
        else:
            missing_bundle.append(skin_id)

    bundled_skin_ids = set(skin_ids_with_bundle)
    character_ids = []
    missing_required_skin = []
    for character in characters:
        character_id = character.get("id") if isinstance(character, dict) else None
        if not isinstance(character_id, int) or isinstance(character_id, bool):
            continue
        required = {character.get("init_skin"), character.get("full_fetter_skin")}
        if required <= bundled_skin_ids:
            character_ids.append(character_id)
        else:
            missing_required_skin.append(character_id)

    usable_character_ids = set(character_ids)
    skin_ids = []
    unavailable_character = []
    for skin in skins:
        skin_id = skin.get("id") if isinstance(skin, dict) else None
        if skin_id not in bundled_skin_ids:
            continue
        if skin.get("character_id") in usable_character_ids:
            skin_ids.append(skin_id)
        else:
            unavailable_character.append(skin_id)

    if not character_ids or not skin_ids:
        raise ValueError("current issuer has no usable character skin resources")
    return {
        "character_ids": character_ids,
        "skin_ids": skin_ids,
        "excluded": {
            "skin_missing_bundle": missing_bundle,
            "skin_unavailable_character": unavailable_character,
            "character_missing_required_skin": missing_required_skin,
        },
    }


def release_version(docs_version: str, product_version: str, bundle_hash: str) -> str:
    """Make every official bundle revision addressable by an immutable release tag."""
    if not re.fullmatch(r"[0-9a-f]{40}", bundle_hash):
        raise ValueError(f"invalid bundle hash: {bundle_hash!r}")
    return f"{docs_version}-{product_version}-{bundle_hash}"


def set_version():
    docs_version = json.loads(
        (DATA_DIR / "client/docs_version/version.json").read_text(encoding="utf-8")
    )["version"]
    metadata = json.loads((DATA_DIR / "meta.json").read_text(encoding="utf-8"))
    version = release_version(
        docs_version,
        metadata["product_version"],
        metadata["bundle_hash"],
    )

    output = os.getenv("GITHUB_OUTPUT")
    if not output:
        raise RuntimeError("GITHUB_OUTPUT is not set")
    with open(output, "a", encoding="utf-8") as file:
        file.write(f"version={version}\n")


def _read_table(relative_path: str):
    return json.loads(
        (DATA_DIR / "tables" / relative_path).read_text(encoding="utf-8")
    )


def _resource_selection(
    audit_path: Path,
    metadata: dict,
    characters: list[dict],
    skins: list[dict],
) -> tuple[list[int], list[int]]:
    report = json.loads(audit_path.read_text(encoding="utf-8"))
    live = report.get("live")
    if not isinstance(live, dict):
        raise ValueError("resource audit is missing live metadata")
    for key in ("issuer", "product_version", "bundle_profile", "bundle_hash"):
        if live.get(key) != metadata.get(key):
            raise ValueError(
                f"resource audit {key}={live.get(key)!r} does not match "
                f"data/meta.json value {metadata.get(key)!r}"
            )

    selection = report.get("selection")
    if not isinstance(selection, dict):
        raise ValueError("resource audit is missing selection")
    character_ids = selection.get("character_ids")
    skin_ids = selection.get("skin_ids")
    if not isinstance(character_ids, list) or not character_ids:
        raise ValueError("resource audit character selection is empty")
    if not isinstance(skin_ids, list) or not skin_ids:
        raise ValueError("resource audit skin selection is empty")
    if len(character_ids) != len(set(character_ids)):
        raise ValueError("resource audit character selection contains duplicates")
    if len(skin_ids) != len(set(skin_ids)):
        raise ValueError("resource audit skin selection contains duplicates")

    characters_by_id = {character["id"]: character for character in characters}
    skins_by_id = {skin["id"]: skin for skin in skins}
    unknown_characters = set(character_ids) - set(characters_by_id)
    unknown_skins = set(skin_ids) - set(skins_by_id)
    if unknown_characters or unknown_skins:
        raise ValueError(
            "resource audit references unknown records: "
            f"characters={sorted(unknown_characters)} skins={sorted(unknown_skins)}"
        )

    selected_skin_ids = set(skin_ids)
    selected_character_ids = set(character_ids)
    broken_characters = [
        character_id
        for character_id in character_ids
        if characters_by_id[character_id].get("init_skin") not in selected_skin_ids
        or characters_by_id[character_id].get("full_fetter_skin")
        not in selected_skin_ids
    ]
    orphan_skins = [
        skin_id
        for skin_id in skin_ids
        if skins_by_id[skin_id].get("character_id") not in selected_character_ids
    ]
    if broken_characters or orphan_skins:
        raise ValueError(
            "resource audit selection is inconsistent: "
            f"characters={broken_characters} orphan_skins={orphan_skins}"
        )
    return character_ids, skin_ids


def set_max_data(resource_audit: Path):
    metadata = json.loads((DATA_DIR / "meta.json").read_text(encoding="utf-8"))
    issuer = metadata["issuer"]
    characters = _read_table("item_definition/character.json")
    skins = _read_table("item_definition/skin.json")
    character_ids, skin_ids = _resource_selection(
        resource_audit,
        metadata,
        characters,
        skins,
    )
    titles = _read_table("item_definition/title.json")
    localized_images = json.loads(
        (DATA_DIR / f"client/docs/localizedImg_{issuer}.json").read_text(
            encoding="utf-8"
        )
    )

    items = _read_table("item_definition/item.json")
    max_data = {
        "character": character_ids,
        "skin": skin_ids,
        "title": title_ids_with_local_assets(titles, localized_images),
        "item": item_ids_with_local_assets(items, localized_images),
    }
    item_loading_images = [
        item["id"]
        for item in items
        if item["category"] == 8
    ]
    max_data["loading_image"] = list(
        set(
            item_loading_images
            + [
                loading_image["id"]
                for loading_image in _read_table(
                    "item_definition/loading_image.json"
                )
            ]
        )
    )
    max_data["emoji"] = {}
    selected_character_ids = set(character_ids)
    for emoji in _read_table("character/emoji.json"):
        if emoji["charid"] in selected_character_ids:
            max_data["emoji"].setdefault(emoji["charid"], []).append(emoji["sub_id"])
    max_data["endings"] = [
        ending["id"] for ending in _read_table("spot/rewards.json")
    ]

    with open("max_data.yaml", "w", encoding="utf-8") as file:
        YAML().dump(max_data, file)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--resource-audit", type=Path, required=True)
    args = parser.parse_args()
    set_version()
    set_max_data(args.resource_audit)


if __name__ == "__main__":
    main()
