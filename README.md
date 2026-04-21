# LC Grind — LeetCode Leaderboard

Static leaderboard for a crew’s LeetCode grind: **GitHub Pages** hosts a single-page UI ([`index.html`](index.html)); stats are refreshed by a script / GitHub Action into [`data.json`](data.json).

**Live demo:** https://nottacoz.github.io/LCtracker

## Local setup

```bash
pip install -r requirements.txt
python fetch_stats.py
# then open index.html in a browser (or use a static server)
open index.html
```

## GitHub Pages

1. Push this repo to GitHub.
2. **Settings → Pages → Build and deployment:** Source = **Deploy from a branch**, Branch = `main` (or default), folder = **/ (root)**.
3. In [`index.html`](index.html), set **`ISSUES_URL`** (comment: “Set ISSUES_URL to your GitHub repo”) so the “Join the Grind” modal points at **Issues → New** for your repository.

## Managing the roster

Edit the `USERNAMES` list in [`fetch_stats.py`](fetch_stats.py), commit, and push. The scheduled workflow (or a manual run) will regenerate [`data.json`](data.json).

## Manual stats refresh

**Actions → Update LeetCode Stats → Run workflow** to fetch latest stats immediately. The workflow also runs daily at **00:30 UTC**.

## Project layout

| File | Purpose |
|------|---------|
| [`index.html`](index.html) | Tailwind CDN + UI, loads `data.json` |
| [`data.json`](data.json) | Cached user stats |
| [`fetch_stats.py`](fetch_stats.py) | LeetCode GraphQL fetcher |
| [`requirements.txt`](requirements.txt) | Python dependency (`requests`) |
| [`.github/workflows/update-stats.yml`](.github/workflows/update-stats.yml) | CI: fetch + commit `data.json` |
