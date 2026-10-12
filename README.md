# Protest digest

Every Monday morning, an email listing the protests planned for the coming week (Monday to Sunday) in
Montreal and Saint-Jean-sur-Richelieu. The top of the email is one line per protest (date and time, title,
location). An annex below holds descriptions, links, other events that week that the filter did not count
as protests, and recent news headlines.

Runs on GitHub Actions (free), so it works with the PC off and needs nothing else. Python standard library only.

## Sources

- [Résistance Montréal calendar](https://www.resistancemontreal.org/calendrier/): community-run activist
  agenda, the main source for dates and places. Events are kept as protests when the title says so (manif,
  rassemblement, marche, vigil, piquetage, grève, …) or when the description does and the title isn't
  obviously something else (atelier, projection, bingo, …). Rules: `PROTEST_TITLE`, `PROTEST_TEXT`,
  `NOT_PROTEST_TITLE` in `digest.py`.
- Google News search (French, Canada) for recent protest coverage in both cities. These are headlines only,
  shown in the annex.

Gaps: union and organization protests announced only on Facebook or Instagram are missed unless someone
adds them to Résistance Montréal. Saint-Jean-sur-Richelieu events rarely appear there; the news section is
the main signal for it.

## Setup

1. Turn on 2-step verification for the Gmail account, then create an app password at
   <https://myaccount.google.com/apppasswords>.
2. Repository secrets (Settings → Secrets and variables → Actions):
   `GMAIL_USER` (the sending Gmail address), `GMAIL_APP_PASSWORD`, and optionally `DIGEST_TO`
   (the recipient; defaults to `GMAIL_USER`).
3. Actions tab → "Weekly protest digest" → "Run workflow" to send one now.

## Local use

    python digest.py --dry-run     # print the digest, write digest.html
    python -m unittest             # offline parser tests

To change the schedule, edit the cron line in `.github/workflows/weekly.yml` (UTC).
