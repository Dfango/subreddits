# Subreddits

## [popular.txt](https://jeffreyca.github.io/subreddits/popular.txt)
List of popular subreddits retrieved using [Reddit's popular subreddits API](https://www.reddit.com/dev/api/#GET_subreddits_{where}). The generator requests up to 5,000 entries and writes every entry Reddit returns; the live API may provide fewer. Updated weekly.

To generate the list yourself, you'll need a Reddit app client ID and secret, which you can get from https://reddit.com/prefs/apps.

### Generate using GitHub Actions
1. Set the following repository secrets ([guide](https://docs.github.com/en/actions/security-for-github-actions/security-guides/using-secrets-in-github-actions#creating-secrets-for-a-repository)) to the values from previous step:
    - `REDDIT_CLIENT_ID`
    - `REDDIT_CLIENT_SECRET`
2. The GitHub Action "Update popular subreddits" is configured to run at 00:00 UTC on Sundays and Wednesdays, but you can also manually trigger it.

### Generate from local machine
1. Install Python 3
2. `pip install -r requirements.txt`
3. Set the `REDDIT_CLIENT_ID` and `REDDIT_CLIENT_SECRET` environment variables
4. `python scripts/gen_popular.py`

## Subriff sources

The Subriff workflow generates separate SFW and NSFW lists from the public growth rankings at [subriff.com](https://subriff.com/). Definitions live in JSON configuration files so new filters can be added without rewriting the generator.

### SFW sources

- [Daily](https://dfango.github.io/subreddits/trending-subriff-daily.txt)
- [Weekly](https://dfango.github.io/subreddits/trending-subriff-weekly.txt)
- [Monthly](https://dfango.github.io/subreddits/trending-subriff-monthly.txt)
- [Blended](https://dfango.github.io/subreddits/trending-subriff-blended.txt) — up to 1,000 weighted entries

Configuration: [`config/subriff-sources.json`](config/subriff-sources.json)

### NSFW sources

- [Daily](https://dfango.github.io/subreddits/trending-subriff-nsfw-daily.txt)
- [Weekly](https://dfango.github.io/subreddits/trending-subriff-nsfw-weekly.txt)
- [Monthly](https://dfango.github.io/subreddits/trending-subriff-nsfw-monthly.txt)
- [Blended](https://dfango.github.io/subreddits/trending-subriff-nsfw-blended.txt)
- [Account Trending](https://dfango.github.io/subreddits/trending-nsfw.txt) — ranked toward current growth
- [Account Random](https://dfango.github.io/subreddits/random-nsfw.txt) — broad daily-shuffled NSFW rotation
- [Account Random NSFW](https://dfango.github.io/subreddits/random-nsfw-explicit.txt) — separate daily-shuffled rotation with a different query mix

Configuration: [`config/subriff-sources-nsfw.json`](config/subriff-sources-nsfw.json)

The outputs are intentionally separate. Every NSFW configuration source requires Subriff's NSFW flag, so these three account-specific lists do not merely include NSFW communities—they filter out rows that are not marked NSFW. The generator deduplicates names case-insensitively, records each community's position in every Subriff result, and ranks candidates with weighted reciprocal rank fusion. Weekly and monthly evidence is weighted slightly more than daily evidence, while the subscriber-size weights reduce the effect of tiny communities with unusually large percentages. Exact score ties use a stable hash instead of alphabetical order, preventing the output from favoring only the beginning of the alphabet.

For Apollo, use the three account-specific URLs as separate sources. Label them `Trending`, `Random`, and `Random NSFW`. `Trending` is ranked by current growth; `Random` is a broad NSFW pool shuffled once per UTC day; and `Random NSFW` uses a different period/size mix and a different daily shuffle seed, so it is not a duplicate of `Random`.

The SFW and NSFW period-specific sources are configured for up to 500 entries each, blended sources for up to 1,000, and the three account-specific sources for up to 1,000. Subriff returns 20 entries per page, so the workflow reads up to 10 pages per query. These are deliberately high-volume settings without making every scheduled run perform the hundreds of requests required to force a 5,000-entry blended list.

The generator waits briefly between Subriff requests and retries temporary HTTP 429/5xx responses with exponential backoff. This keeps the larger source set within Subriff's practical rate limits; it does not bypass those limits.

Each source also has a matching `subriff-ranking-*.json` report containing the score, best observed rank, appearance count, periods, size filters, and whether the candidate made the plaintext output. The reports are for inspection; Apollo still receives only one subreddit name per line. Identical queries are cached during a generation run, so the blended sources do not refetch the same Subriff pages.

### Generate locally

~~~sh
python3 -m pip install -r requirements.txt
python3 -m unittest discover -s tests -v
python3 scripts/gen_trending_subriff.py --all
python3 scripts/gen_trending_subriff.py --config config/subriff-sources-nsfw.json --all
~~~
