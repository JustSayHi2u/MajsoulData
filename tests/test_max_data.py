import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from get_max_data import (
    deduplicate_head_frames,
    has_expired_name,
    _resource_selection,
    item_ids_with_local_assets,
    release_version,
    select_character_skin_resources,
    title_ids_with_local_assets,
)


class MaxDataTests(unittest.TestCase):
    def test_character_and_skin_selection_requires_live_bundle_assets(self):
        characters = [
            {"id": 200001, "init_skin": 400101, "full_fetter_skin": 400102},
            {"id": 200002, "init_skin": 400201, "full_fetter_skin": 400202},
            {"id": 200003, "init_skin": 400301, "full_fetter_skin": 400302},
        ]
        skins = [
            {"id": 400101, "character_id": 200001, "path": "deco/character/a"},
            {"id": 400102, "character_id": 200001, "path": "deco/character/a_0"},
            {"id": 400103, "character_id": 200001, "path": "deco/character/a_alt"},
            {"id": 400201, "character_id": 200002, "path": "deco/character/b"},
            {"id": 400202, "character_id": 200002, "path": "deco/character/b_0"},
            {"id": 400203, "character_id": 200002, "path": "deco/character/b_alt"},
            {"id": 400301, "character_id": 200003, "path": "deco/character/c"},
            {"id": 400302, "character_id": 200003, "path": "deco/character/c_0"},
            {"id": 400303, "character_id": 200003, "path": "deco/character/c_alt"},
        ]
        bundle_paths = {
            "MyAssets/Deco/Character/A/prefab.prefab",
            "myassets/deco/character/a_0/spine.atlas",
            "myassets/deco/character/a_alt/spine.atlas",
            "myassets/deco/character/b_0/spine.atlas",
            "myassets/deco/character/b_alt/spine.atlas",
            "myassets/deco/character/c/spine.atlas",
            "myassets/deco/character/c_0/spine.atlas",
        }

        selection = select_character_skin_resources(characters, skins, bundle_paths)

        self.assertEqual(selection["character_ids"], [200001, 200003])
        self.assertEqual(
            selection["skin_ids"],
            [400101, 400102, 400103, 400301, 400302],
        )
        self.assertEqual(
            selection["excluded"]["skin_missing_bundle"],
            [400201, 400303],
        )
        self.assertEqual(
            selection["excluded"]["skin_unavailable_character"],
            [400202, 400203],
        )
        self.assertEqual(
            selection["excluded"]["character_missing_required_skin"],
            [200002],
        )

    def test_resource_selection_rejects_stale_bundle_audit(self):
        metadata = {
            "issuer": "chs_t",
            "product_version": "4.0.47",
            "bundle_profile": "ASTC",
            "bundle_hash": "a" * 40,
        }
        report = {
            "live": {**metadata, "bundle_hash": "b" * 40},
            "selection": {"character_ids": [200001], "skin_ids": [400101, 400102]},
        }
        characters = [
            {"id": 200001, "init_skin": 400101, "full_fetter_skin": 400102}
        ]
        skins = [
            {"id": 400101, "character_id": 200001},
            {"id": 400102, "character_id": 200001},
        ]
        with TemporaryDirectory() as directory:
            path = Path(directory) / "audit.json"
            path.write_text(json.dumps(report), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "bundle_hash"):
                _resource_selection(path, metadata, characters, skins)

    def test_release_version_changes_when_only_bundle_hash_changes(self):
        first = release_version("0.16.267", "4.0.46", "a" * 40)
        second = release_version("0.16.267", "4.0.46", "b" * 40)

        self.assertEqual(first, f"0.16.267-4.0.46-{'a' * 40}")
        self.assertNotEqual(first, second)

    def test_release_version_rejects_invalid_bundle_hash(self):
        with self.assertRaises(ValueError):
            release_version("0.16.267", "4.0.46", "not-a-bundle-hash")

    def test_title_ids_require_icon_in_current_issuer_assets(self):
        titles = [
            {"id": 600001, "icon": "deco/title/shared/pic/shared.png"},
            {"id": 600002, "icon": "deco/title/jp_only/pic/jp_only.png"},
        ]
        localized_images = {
            "items": [
                {
                    "filepath": "deco\\title\\shared\\pic\\shared.png",
                    "fileType": 1,
                }
            ]
        }

        self.assertEqual(
            title_ids_with_local_assets(titles, localized_images),
            [600001],
        )

    def test_title_ids_fail_when_locale_index_is_empty(self):
        with self.assertRaises(ValueError):
            title_ids_with_local_assets(
                [{"id": 600001, "icon": "deco/title/shared.png"}],
                {"items": []},
            )

    def test_item_ids_drop_expired_tombstones_and_cross_region_assets(self):
        items = [
            {"id": 305007, "category": 5, "icon": "deco/effect/ron.jpg"},
            {"id": 305214, "category": 5, "icon": None},
            {
                "id": 30990016,
                "category": 5,
                "icon": "deco/hand/legacy.jpg",
                "name": {"chs": "手-赤麟(已过期)"},
            },
            {"id": 30580025, "category": 5, "icon": "deco/kr/table.jpg"},
            {"id": 999999, "category": 8, "icon": "deco/loading.jpg"},
        ]
        localized_images = {
            "items": [
                {"filepath": "deco\\effect\\ron.jpg", "fileType": 1},
                {"filepath": "deco/hand/legacy.jpg", "fileType": 1},
                {"filepath": "deco/loading.jpg", "fileType": 1},
            ]
        }

        self.assertEqual(
            item_ids_with_local_assets(items, localized_images),
            [305007],
        )

    def test_item_ids_drop_records_after_official_expiry(self):
        items = [
            {
                "id": 305712,
                "category": 5,
                "icon": "deco/mjpai/rml.jpg",
                "item_expire": "2023-06-01 00:00:00",
            },
            {
                "id": 30550046,
                "category": 5,
                "icon": "deco/head/future.jpg",
                "item_expire": "2028-01-01 05:00:00",
            },
        ]
        localized_images = {
            "items": [
                {"filepath": "deco/mjpai/rml.jpg"},
                {"filepath": "deco/head/future.jpg"},
            ]
        }
        now = datetime(2026, 8, 21, tzinfo=timezone(timedelta(hours=8)))

        self.assertEqual(
            item_ids_with_local_assets(items, localized_images, now=now),
            [30550046],
        )

    def test_expired_name_detection_is_locale_aware(self):
        self.assertTrue(has_expired_name({"name": {"chs": "手-赤麟(已过期)"}}))
        self.assertTrue(has_expired_name({"name": {"en": "Legacy Hand (Expired)"}}))
        self.assertFalse(has_expired_name({"name": {"chs": "橘猫爪"}}))

    def test_head_frames_keep_one_visual_revision_without_touching_other_items(self):
        items = [
            {
                "id": 305510,
                "category": 5,
                "type": 5,
                "icon": "deco/head/frame.jpg",
                "item_expire": "2021-07-01 05:00:00",
            },
            {
                "id": 30550046,
                "category": 5,
                "type": 5,
                "icon": "deco/head/frame.jpg",
                "item_expire": "2028-01-01 05:00:00",
            },
            {
                "id": 305500,
                "category": 5,
                "type": 5,
                "icon": "deco/head/sprout.jpg",
                "item_expire": None,
            },
            {
                "id": 305555,
                "category": 5,
                "type": 5,
                "icon": "deco/head/sprout.jpg",
                "item_expire": "2020-05-24 05:00:00",
            },
            {
                "id": 305025,
                "category": 5,
                "type": 4,
                "icon": "deco/music/shared.jpg",
                "item_expire": None,
            },
            {
                "id": 305026,
                "category": 5,
                "type": 4,
                "icon": "deco/music/shared.jpg",
                "item_expire": None,
            },
        ]

        self.assertEqual(
            [item["id"] for item in deduplicate_head_frames(items)],
            [30550046, 305500, 305025, 305026],
        )


if __name__ == "__main__":
    unittest.main()
