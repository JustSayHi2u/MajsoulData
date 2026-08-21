import unittest

from get_max_data import (
    item_ids_with_local_assets,
    release_version,
    title_ids_with_local_assets,
)


class MaxDataTests(unittest.TestCase):
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
            {"id": 30580025, "category": 5, "icon": "deco/kr/table.jpg"},
            {"id": 999999, "category": 8, "icon": "deco/loading.jpg"},
        ]
        localized_images = {
            "items": [
                {"filepath": "deco\\effect\\ron.jpg", "fileType": 1},
                {"filepath": "deco/loading.jpg", "fileType": 1},
            ]
        }

        self.assertEqual(
            item_ids_with_local_assets(items, localized_images),
            [305007],
        )


if __name__ == "__main__":
    unittest.main()
