# Protest calendar

Upcoming protests in Montreal and Saint-Jean-sur-Richelieu as a calendar you subscribe to, plus a web page
with the next 7 days.

- `docs/protests.ics`: protests for the next 60 days. Each event has the title, time, place, a description
  and links. Subscribe to it by URL in any calendar app (Proton Calendar, Thunderbird, Google Calendar,
  Outlook, phone calendars); it refreshes on its own.
- `docs/index.html`: the next 7 days as a short list (date and time, title, place). An annex below holds
  descriptions, other events that the filter did not count as protests, and recent news headlines.

GitHub Actions regenerates both every morning and commits them; GitHub Pages serves them at
`https://david-gilbert-cs.github.io/protest-digest/` and `.../protests.ics`. Python standard library only,
no accounts or secrets. If the source can't be read, the run fails and the previous files stay published.

## Sources

- [Résistance Montréal calendar](https://www.resistancemontreal.org/calendrier/): community-run activist
  agenda, the main source for dates and places. Events are kept as protests when the title says so (manif,
  rassemblement, marche, vigil, piquetage, grève, …) or when the description does and the title isn't
  obviously something else (atelier, projection, bingo, …). Rules: `PROTEST_TITLE`, `PROTEST_TEXT`,
  `NOT_PROTEST_TITLE` in `digest.py`.
- Google News search (French, Canada) for recent protest coverage in both cities. These are headlines only,
  shown on the web page.

Gaps: protests announced only on Facebook or Instagram are missed unless someone adds them to Résistance
Montréal. Saint-Jean-sur-Richelieu events rarely appear there; the news section is the main signal for it.

## Setup (once)

1. Repo must be public (GitHub Pages on a private repo needs a paid plan).
2. Settings → Pages → Source "Deploy from a branch", branch `main`, folder `/docs`.
3. Actions tab → "Update protest calendar" → "Run workflow".
4. In your calendar app, add a calendar from URL:
   `https://david-gilbert-cs.github.io/protest-digest/protests.ics`

## Local use

    python digest.py           # write docs/protests.ics and docs/index.html
    python digest.py --print   # print the 7-day list as text
    python -m unittest         # offline tests

Times are written in UTC when the Python time-zone database is available (it is on GitHub's runners; on
Windows, `pip install tzdata`), otherwise as floating local time.
