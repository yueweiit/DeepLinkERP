import json
import unittest

from phone_watch.config import DEFAULT_NEWS_CONFIG
from phone_watch.config import load_news_config


def write_news_config(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class NewsConfigTests(unittest.TestCase):
    def make_path(self):
        from pathlib import Path
        import tempfile

        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return Path(directory.name) / "news_sources.json"

    def full_keywords(self):
        return {
            "ZTE": ["中兴手机", "努比亚", "红魔"],
            "MOTOROLA": ["摩托罗拉"],
            "XIAOMI": ["小米"],
            "SAMSUNG": ["三星手机"],
            "OPPO": ["OPPO"],
            "HONOR": ["荣耀"],
            "VIVO": ["vivo"],
            "HUAWEI": ["华为手机"],
        }

    def test_load_news_config_normalizes_sources_and_keywords(self):
        config_path = self.make_path()
        write_news_config(
            config_path,
            {
                "retention_days": 9,
                "fallback_limit": 4,
                "brand_keywords": self.full_keywords(),
                "sources": [
                    {
                        "brand": "vivo",
                        "source_type": "ithome_brand_search",
                        "source_name": "IT之家品牌关键词搜索",
                        "start_urls": ["https://www.ithome.com/tags/vivo/"],
                        "render": True,
                    },
                    {
                        "brand": "all",
                        "source_type": "ithome_phone_today",
                        "source_name": "IT之家手机分区当日新闻",
                        "start_urls": ["https://www.ithome.com/category/phone"],
                    },
                ],
            },
        )

        config = load_news_config(config_path)

        self.assertEqual(config.retention_days, 9)
        self.assertEqual(config.fallback_limit, 4)
        self.assertEqual(config.brand_keywords["ZTE"], ("中兴手机", "努比亚", "红魔"))
        self.assertEqual(config.brand_keywords["VIVO"], ("vivo",))
        self.assertEqual(config.brand_keywords["HUAWEI"], ("华为手机",))
        self.assertEqual(config.sources[0].brand, "VIVO")
        self.assertEqual(config.sources[0].source_type, "ithome_brand_search")
        self.assertEqual(config.sources[0].start_urls, ("https://www.ithome.com/tags/vivo/",))
        self.assertTrue(config.sources[0].render)
        self.assertEqual(config.sources[1].brand, "ALL")

    def test_load_news_config_uses_defaults(self):
        config_path = self.make_path()
        write_news_config(
            config_path,
            {
                "brand_keywords": self.full_keywords(),
                "sources": [],
            },
        )

        config = load_news_config(config_path)

        self.assertEqual(config.retention_days, 7)
        self.assertEqual(config.fallback_limit, 3)

    def test_load_news_config_rejects_unknown_source_type(self):
        config_path = self.make_path()
        write_news_config(
            config_path,
            {
                "brand_keywords": self.full_keywords(),
                "sources": [{"brand": "VIVO", "source_type": "bad", "source_name": "Bad"}],
            },
        )

        with self.assertRaisesRegex(ValueError, "source_type"):
            load_news_config(config_path)

    def test_load_news_config_rejects_official_source_type(self):
        config_path = self.make_path()
        write_news_config(
            config_path,
            {
                "brand_keywords": self.full_keywords(),
                "sources": [
                    {
                        "brand": "VIVO",
                        "source_type": "official",
                        "source_name": "vivo Global News",
                        "start_urls": ["https://www.vivo.com/en/news"],
                    }
                ],
            },
        )

        with self.assertRaisesRegex(ValueError, "Unsupported news source_type: official"):
            load_news_config(config_path)

    def test_load_news_config_requires_all_brand_keywords(self):
        config_path = self.make_path()
        write_news_config(
            config_path,
            {
                "brand_keywords": {
                    "ZTE": ["中兴手机", "努比亚", "红魔"],
                },
                "sources": [],
            },
        )

        with self.assertRaisesRegex(ValueError, "brand_keywords"):
            load_news_config(config_path)

    def test_default_ithome_brand_sources_use_keyword_search_configuration(self):
        config = load_news_config(DEFAULT_NEWS_CONFIG)
        self.assertNotIn("official", {source.source_type for source in config.sources})
        brand_sources = {
            source.brand: source
            for source in config.sources
            if source.source_type == "ithome_brand_search"
        }

        self.assertEqual(
            set(brand_sources),
            {"MOTOROLA", "OPPO", "VIVO", "HONOR", "XIAOMI", "ZTE", "SAMSUNG", "HUAWEI"},
        )
        self.assertEqual(
            config.brand_keywords["ZTE"],
            ("中兴手机", "努比亚", "红魔"),
        )
        self.assertEqual(config.brand_keywords["HUAWEI"], ("华为手机",))
        self.assertTrue(all(source.source_name == "IT之家品牌关键词搜索" for source in brand_sources.values()))
        self.assertTrue(all(source.start_urls == () for source in brand_sources.values()))
        self.assertTrue(all(not source.render for source in brand_sources.values()))
        self.assertEqual(brand_sources["MOTOROLA"].search_keywords, ("摩托罗拉",))
        self.assertEqual(brand_sources["VIVO"].search_keywords, ("vivo",))
        self.assertEqual(
            brand_sources["ZTE"].search_keywords,
            ("中兴手机", "努比亚", "红魔"),
        )
