# VEYLO — automated YouTube Shorts starter

This package replaces the demo-only workflow with a scheduled, source-linked Shorts pipeline.

## What it does
1. Reads recent items from a small allowlist of public RSS feeds (NASA, Smithsonian, ScienceDaily).
2. Selects a recent item not already used.
3. Writes a short narration from the feed title/summary and retains the source URL.
4. Generates English speech with Edge TTS (no API key).
5. Downloads a relevant image from Wikimedia Commons (or uses a generated text-card fallback).
6. Renders a vertical MP4 with FFmpeg and burned-in captions.
7. Optionally uploads it to YouTube using official OAuth credentials.

## Important limitations
- This is an initial reliable pipeline, not an autonomous fact-checking journalist. It uses the publisher's RSS title/summary and includes the source in the description. Review factual claims before enabling public uploads.
- Edge TTS and public RSS/Wikimedia endpoints are third-party services and may change or rate-limit.
- YouTube upload requires OAuth credentials and an authorized Google account. GitHub Actions cannot bypass YouTube API restrictions. New/unverified API projects may have upload restrictions.
- GitHub-hosted runners have usage limits. This is not guaranteed unlimited or cost-free at any scale.
- The default workflow renders and stores an artifact; publishing is OFF until `PUBLISH_TO_YOUTUBE` is set to `true`.

## Setup in GitHub (one-time)
1. Upload the contents of this ZIP into the root of `666no666/automatic-shorts` (keep the `.github` folder).
2. In repository Settings → Secrets and variables → Actions, add:
   - `YOUTUBE_CLIENT_SECRETS`: full contents of your Google OAuth `client_secret.json`
   - `YOUTUBE_TOKEN_JSON`: OAuth token JSON created after granting YouTube upload permission
3. In Settings → Variables → Actions, add:
   - `PUBLISH_TO_YOUTUBE` = `true` only after OAuth is configured and you have tested a private upload.
   - `YOUTUBE_PRIVACY_STATUS` = `private` initially (`unlisted` or `public` only after review)
4. Actions → VEYLO Daily Shorts → Run workflow. Inspect the MP4 artifact.
5. Enable scheduled runs in `.github/workflows/veylo.yml` (the schedule is already present).

Do not paste credentials into chat or commit them to the repository. If you cannot create OAuth credentials, leave publishing disabled; video creation still works.

## Local run
Python 3.11+, FFmpeg:
```bash
pip install -r requirements.txt
python -m veylo.main
```
Output goes to `output/`.

## Schedule
The workflow is scheduled daily at 14:00 UTC. Edit the cron expression if needed.
