# Subreddits

## [popular.txt](https://jeffreyca.github.io/subreddits/popular.txt)
List of popular subreddits retrieved using [Reddit's popular subreddits API](https://www.reddit.com/dev/api/#GET_subreddits_{where}). Updated weekly.

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
- [Blended](https://dfango.github.io/subreddits/trending-subriff-blended.txt) — existing 35-item source

Configuration: [`config/subriff-sources.json`](config/subriff-sources.json)

### NSFW sources

- [Daily](https://dfango.github.io/subreddits/trending-subriff-nsfw-daily.txt)
- [Weekly](https://dfango.github.io/subreddits/trending-subriff-nsfw-weekly.txt)
- [Monthly](https://dfango.github.io/subreddits/trending-subriff-nsfw-monthly.txt)
- [Blended](https://dfango.github.io/subreddits/trending-subriff-nsfw-blended.txt)

Configuration: [`config/subriff-sources-nsfw.json`](config/subriff-sources-nsfw.json)

The outputs are intentionally separate. The generator deduplicates names case-insensitively, records each community's position in every Subriff result, and ranks candidates with weighted reciprocal rank fusion. Weekly and monthly evidence is weighted slightly more than daily evidence, while the subscriber-size weights reduce the effect of tiny communities with unusually large percentages. Exact score ties use a stable hash instead of alphabetical order, preventing the output from favoring only the beginning of the alphabet.

Each source also has a matching `subriff-ranking-*.json` report containing the score, best observed rank, appearance count, periods, size filters, and whether the candidate made the plaintext output. The reports are for inspection; Apollo still receives only one subreddit name per line. Identical queries are cached during a generation run, so the blended sources do not refetch the same Subriff pages.

### Generate locally

~~~sh
python3 -m pip install -r requirements.txt
python3 -m unittest discover -s tests -v
python3 scripts/gen_trending_subriff.py --all
python3 scripts/gen_trending_subriff.py --config config/subriff-sources-nsfw.json --all
~~~

## [trending-gummy-daily.txt](https://jeffreyca.github.io/subreddits/trending-gummy-daily.txt), [trending-gummy-weekly.txt](https://jeffreyca.github.io/subreddits/trending-gummy-weekly.txt)
List of trending subreddits, sourced from [gummysearch.com](https://gummysearch.com/tools/top-subreddits/). **No longer updated.**

* Growth period: daily, weekly
* Size: large, huge, massive

### Generate using GitHub Actions
The GitHub Action "Update trending subreddits (gummysearch)" is configured to run twice a day, but you can also manually trigger it.

### Generate from local machine
1. `./scripts/gen_trending_gummy.sh <daily or weekly>`

## [trending-reddstats-daily.txt](https://jeffreyca.github.io/subreddits/trending-reddstats-daily.txt), [trending-reddstats-weekly.txt](https://jeffreyca.github.io/subreddits/trending-reddstats-weekly.txt)
List of trending subreddits, sourced from [reddstats.com](https://reddstats.com/ranking/relative?over18=False&period=daily&subscriber_classification=50001-100000). **No longer updated.**

## [trending-apollo.txt](https://jeffreyca.github.io/subreddits/trending-apollo.txt)
Original list of trending subreddits used by Apollo iOS app, extracted from `trending-subreddits.plist`. Last updated 2023-09-09.
