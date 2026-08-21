import json
import os
import re
from pathlib import Path

from ruamel.yaml import YAML


DATA_DIR = Path("data")


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


def item_ids_with_local_assets(items: list[dict], localized_images: dict) -> list[int]:
    """Drop expired tombstones and cross-region decorations without local icons."""
    decorations = [item for item in items if item.get("category") == 5]
    return ids_with_local_assets(decorations, localized_images)


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


def set_max_data():
    metadata = json.loads((DATA_DIR / "meta.json").read_text(encoding="utf-8"))
    issuer = metadata["issuer"]
    titles = _read_table("item_definition/title.json")
    localized_images = json.loads(
        (DATA_DIR / f"client/docs/localizedImg_{issuer}.json").read_text(
            encoding="utf-8"
        )
    )

    items = _read_table("item_definition/item.json")
    max_data = {
        "character": [
            character["id"]
            for character in _read_table("item_definition/character.json")
        ],
        "skin": [
            skin["id"] for skin in _read_table("item_definition/skin.json")
        ],
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
    for emoji in _read_table("character/emoji.json"):
        max_data["emoji"].setdefault(emoji["charid"], []).append(emoji["sub_id"])
    max_data["endings"] = [
        ending["id"] for ending in _read_table("spot/rewards.json")
    ]

    with open("max_data.yaml", "w", encoding="utf-8") as file:
        YAML().dump(max_data, file)


def main():
    set_version()
    set_max_data()


if __name__ == "__main__":
    main()
