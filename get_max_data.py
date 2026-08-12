import json
import os
from pathlib import Path

from ruamel.yaml import YAML


DATA_DIR = Path("data")


def _normalized_asset_path(path: str) -> str:
    return path.replace("\\", "/").lstrip("/").lower()


def title_ids_with_local_assets(titles: list[dict], localized_images: dict) -> list[int]:
    """Return title IDs whose icon is shipped by the current client issuer."""
    items = localized_images.get("items")
    if not isinstance(items, list):
        raise ValueError("localizedImg is missing items")
    asset_paths = {
        _normalized_asset_path(item["filepath"])
        for item in items
        if isinstance(item, dict) and isinstance(item.get("filepath"), str)
    }
    title_ids = [
        title["id"]
        for title in titles
        if isinstance(title, dict)
        and isinstance(title.get("id"), int)
        and not isinstance(title.get("id"), bool)
        and isinstance(title.get("icon"), str)
        and _normalized_asset_path(title["icon"]) in asset_paths
    ]
    if not title_ids:
        raise ValueError("current issuer has no usable title icons")
    return title_ids


def set_version():
    docs_version = json.loads(
        (DATA_DIR / "client/docs_version/version.json").read_text(encoding="utf-8")
    )["version"]
    product_version = json.loads(
        (DATA_DIR / "meta.json").read_text(encoding="utf-8")
    )["product_version"]

    output = os.getenv("GITHUB_OUTPUT")
    if not output:
        raise RuntimeError("GITHUB_OUTPUT is not set")
    with open(output, "a", encoding="utf-8") as file:
        file.write(f"version={docs_version}-{product_version}\n")


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

    max_data = {
        "character": [
            character["id"]
            for character in _read_table("item_definition/character.json")
        ],
        "skin": [
            skin["id"] for skin in _read_table("item_definition/skin.json")
        ],
        "title": title_ids_with_local_assets(titles, localized_images),
        "item": [
            item["id"]
            for item in _read_table("item_definition/item.json")
            if item["category"] == 5
        ],
    }
    item_loading_images = [
        item["id"]
        for item in _read_table("item_definition/item.json")
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
