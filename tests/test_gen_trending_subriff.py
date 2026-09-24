import unittest
from unittest.mock import patch

import requests

from scripts import gen_trending_subriff as generator


class GeneratorTests(unittest.TestCase):
    def test_ranked_deduplication_and_period_weights(self):
        source = {
            "name": "test",
            "size_filters": ["medium"],
            "periods": ["daily", "weekly"],
            "limit": 10,
        }

        def fake_fetch(session, query, max_pages):
            if query["sort_by"] == "daily":
                return [
                    {"name": "Alpha", "key": "alpha", "rank": 1},
                    {"name": "Beta", "key": "beta", "rank": 2},
                ]
            return [
                {"name": "beta", "key": "beta", "rank": 1},
                {"name": "Gamma", "key": "gamma", "rank": 30},
            ]

        with patch.object(generator, "fetch_subreddit_observations", side_effect=fake_fetch):
            result = generator.generate_source(source, {}, requests.Session())

        self.assertEqual(result[:3], ["Beta", "Gamma", "Alpha"])

    def test_rank_position_beats_alphabetical_order(self):
        source = {"name": "test", "size_filters": ["medium"], "periods": ["daily"], "limit": 2}

        def fake_fetch(session, query, max_pages):
            return [
                {"name": "Zebra", "key": "zebra", "rank": 1},
                {"name": "Alpha", "key": "alpha", "rank": 2},
            ]

        with patch.object(generator, "fetch_subreddit_observations", side_effect=fake_fetch):
            result = generator.generate_source(source, {}, requests.Session())

        self.assertEqual(result, ["Zebra", "Alpha"])

    def test_exact_score_ties_use_stable_hash_not_alphabetical_order(self):
        source = {
            "name": "test",
            "size_filters": ["medium"],
            "periods": ["daily", "weekly"],
            "limit": 2,
            "scoring": {
                "period_weights": {"daily": 1.0, "weekly": 1.0},
                "size_weights": {"medium": 1.0},
            },
        }

        def fake_fetch(session, query, max_pages):
            name = "Alpha" if query["sort_by"] == "daily" else "Zebra"
            key = name.casefold()
            return [{"name": name, "key": key, "rank": 1}]

        with patch.object(generator, "fetch_subreddit_observations", side_effect=fake_fetch):
            result = generator.generate_source(source, {}, requests.Session())

        expected = sorted(
            ["Alpha", "Zebra"],
            key=lambda name: generator._stable_tie_key(name, "subriff-v2"),
        )
        self.assertEqual(result, expected)

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
