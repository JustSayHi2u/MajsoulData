import unittest

from scripts.check_live_version import choose_url, live_metadata


class LiveVersionTests(unittest.TestCase):
    def test_choose_url_prefers_priority_then_weight(self):
        self.assertEqual(
            choose_url(
                [
                    {"url": "https://low.example/", "Priority": 1, "weight": 99},
                    {"url": "https://high.example/", "Priority": 2, "weight": 1},
                ]
            ),
            "https://high.example/",
        )

    def test_live_metadata_resolves_official_bundle_hash(self):
        metadata = {
            "client_url": "https://game.example/1/",
            "issuer": "chs_t",
            "bundle_profile": "ASTC",
        }
        json_documents = {
            "https://game.example/assetbundles/clientBundleSettings/chs_t-release.json": {
                "warehouses": [
                    {
                        "urls": [{"url": "https://config.example/base/"}],
                        "warehouseSettingPath": "warehouse.json",
                    }
                ]
            },
            "https://config.example/base/warehouse.json": {
                "urls": [{"url": "https://assets.example/"}],
                "bundlePath": "bundles",
            },
        }

        def text_loader(url, _timeout):
            if url == metadata["client_url"]:
                return "productVersion: '4.0.46'"
            if url == "https://assets.example/bundles/ASTC/bundle_hash.txt":
                return "a" * 40
            raise AssertionError(url)

        def json_loader(url, _timeout):
            return json_documents[url]

        self.assertEqual(
            live_metadata(
                metadata,
                text_loader=text_loader,
                json_loader=json_loader,
            ),
            {"product_version": "4.0.46", "bundle_hash": "a" * 40},
        )


if __name__ == "__main__":
    unittest.main()
