import unittest
from unittest.mock import patch

import requests

from scripts import gen_trending_subriff as generator


class GeneratorTests(unittest.TestCase):
    def test_case_insensitive_deduplication_and_deterministic_ties(self):
        source = {"name": "test", "size_filters": ["medium"], "periods": ["daily", "weekly"], "limit": 10}

        def fake_fetch(session, query, max_pages):
            return ["r/Alpha", "Beta"] if query["sort_by"] == "daily" else ["beta", "Gamma"]

        with patch.object(generator, "fetch_subreddits", side_effect=fake_fetch):
            result = generator.generate_source(source, {}, requests.Session())

        self.assertEqual(result, ["Beta", "Alpha", "Gamma"])

    def test_sfw_filter_checks_all_known_flags(self):
        for flag in ("isNsfw", "internal_IsNsfw", "suggested_Internal_IsNsfw"):
            self.assertFalse(generator._is_allowed({flag: True}, include_nsfw=False))
        self.assertTrue(generator._is_allowed({"isNsfw": True}, include_nsfw=True))

    def test_configs_keep_sfw_and_nsfw_outputs_separate(self):
        sfw = generator.load_config(generator.DEFAULT_CONFIG)
        nsfw = generator.load_config(generator.DEFAULT_CONFIG.with_name("subriff-sources-nsfw.json"))
        self.assertEqual(sfw["content_policy"], "sfw")
        self.assertEqual(nsfw["content_policy"], "nsfw")
        self.assertTrue(all("nsfw" not in source["output"] for source in sfw["sources"]))
        self.assertTrue(all("nsfw" in source["output"] for source in nsfw["sources"]))


if __name__ == "__main__":
    unittest.main()
