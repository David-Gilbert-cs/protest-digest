"""Upcoming protests in Montreal and Saint-Jean-sur-Richelieu as a calendar feed and a web page.
Standard library only.

  python digest.py            write docs/protests.ics (next CALENDAR_DAYS days) and docs/index.html (next 7 days)
  python digest.py --print    print the 7-day digest as text instead

If the event source can't be read, nothing is written and the exit code is non-zero, so a bad run never
empties the published calendar.
"""

import argparse
import hashlib
import html
import re
import sys
import unicodedata
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

try:
    from zoneinfo import ZoneInfo

    TZ = ZoneInfo("America/Montreal")
except Exception:  # no tz database (e.g. Windows without tzdata): fall back to local time
    TZ = None

RM_BASE = "https://www.resistancemontreal.org/"
RM_CALENDAR = RM_BASE + "calendrier/"
NEWS_QUERIES = {
    "Saint-Jean-sur-Richelieu": '"Saint-Jean-sur-Richelieu" (manifestation OR manifestants OR rassemblement OR grève OR piquetage) when:14d',
    "Montréal": "Montréal (manifestation OR manifestants OR rassemblement) when:7d",
}
NEWS_PER_CITY = 8
UA = "Mozilla/5.0 (protest-digest; personal calendar feed)"
CALENDAR_DAYS = 60
OUT_DIR = Path(__file__).with_name("docs")

# Matched against accent-free lowercase text.
PROTEST_TITLE = re.compile(
    r"\b(manif\w*|rassemblement\w*|march|rally|protest\w*|vigil\w*|vigile\w*|piquet\w*|picket\w*|greve\w*|"
    r"strike|occupation|die-in|blocage|blockade|demo|demonstration|journee d.action|day of action|"
    r"contre-manif\w*|commemoration|sit-in|teach-in)\b")
PROTEST_TEXT = re.compile(
    r"\b(manifestation|manif|rassemblement|protest|rally|vigil|vigile|piquetage|picket line|on marche|marchons|"
    r"we march|demonstration|die-in|sit-in)\b")
NOT_PROTEST_TITLE = re.compile(
    r"\b(bookfair|salon du livre|projection|screening|atelier|workshop|bingo|lancement|launch|causerie|conference|"
    r"formation|training|souper|potluck|film|fundraiser|benefice|cafe|concert|show|spectacle|assemblee|meeting|"
    r"reunion|club de lecture|reading group|cours|course|upop|convergence|panel|discussion)\b")
# "marche" (a march) is matched before folding so "marché" (a market) does not count.
MARCHE = re.compile(r"\bmarches?\b")
SJSR = re.compile(r"saint-jean-sur-richelieu|st-jean-sur-richelieu|\bst-jean\b|\bsaint-jean\b(?!-baptiste)")

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


@dataclass
class Event:
    title: str
    start: datetime
    location: str = ""
    location_detail: str = ""
    official_url: str = ""
    source_url: str = ""
    description: str = ""
    city: str = "Montréal"
    is_protest: bool = False


@dataclass
class Digest:
    start: date
    end: date
    protests: list = field(default_factory=list)
    others: list = field(default_factory=list)
    news: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)
    calendar: list = field(default_factory=list)  # protests over the next CALENDAR_DAYS days
    source_ok: bool = False


def fold(s):
    """Lowercase without accents, for keyword matching."""
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")


def text(fragment):
    s = re.sub(r"<br[^>]*>", "\n", fragment)
    s = re.sub(r"</p>", "\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s).replace("\xa0", " ")
    return "\n".join(" ".join(line.split()) for line in s.splitlines() if line.strip())


def fetch(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode(r.headers.get_content_charset() or "utf-8", errors="replace")


def classify(ev):
    title, body = fold(ev.title), fold(ev.description)
    if PROTEST_TITLE.search(title) or MARCHE.search(ev.title.lower()):
        ev.is_protest = True
    elif not NOT_PROTEST_TITLE.search(title) and PROTEST_TEXT.search(body):
        ev.is_protest = True
    where = fold(" ".join([ev.title, ev.location, ev.location_detail]))
    if SJSR.search(where):
        ev.city = "Saint-Jean-sur-Richelieu"
    return ev


def parse_rm_calendar(page):
    """Events from Résistance Montréal's calendar page (one `one_event = {...}` block plus modal per event)."""
    events = []
    for chunk in page.split("one_event = {")[1:]:
        start = re.search(r"start:\s*'(\d{4}-\d{2}-\d{2})(?: (\d{2}:\d{2}))?", chunk)
        title = re.search(r"<h1>(.*?)</h1>", chunk, re.S)
        if not start or not title:
            continue
        when = datetime.fromisoformat(f"{start.group(1)}T{start.group(2) or '00:00'}")
        ev = Event(title=text(title.group(1)).strip(), start=when)
        loc = re.search(r'glyphicon-map-marker"></i>(.*?)</a>\s*(?:<p>(.*?)</p>)?', chunk, re.S)
        if loc:
            ev.location = text(loc.group(1))
            ev.location_detail = text(loc.group(2) or "")
        official = re.search(r'button-event-link[^"]*"\s+href="([^"]+)"', chunk)
        if official:
            ev.official_url = html.unescape(official.group(1))
        own = re.search(r'href="(evenement/[^"]+)"', chunk)
        if own:
            ev.source_url = RM_BASE + own.group(1)
            rest = chunk[own.end():]
            rest = rest.split("</p>", 1)[1] if "</p>" in rest else rest
            ev.description = text(rest.split("`;", 1)[0])
        events.append(classify(ev))
    return events


def parse_news(xml_text, limit=NEWS_PER_CITY):
    items = []
    for item in ET.fromstring(xml_text).iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        when = item.findtext("pubDate")
        try:
            when = parsedate_to_datetime(when).date() if when else None
        except (TypeError, ValueError):
            when = None
        if title and link:
            items.append({"title": title, "link": link, "date": when})
    return items[:limit]


def today():
    return datetime.now(TZ).date() if TZ else date.today()


def build(start=None, days=7):
    start = start or today()
    end = start + timedelta(days=days - 1)
    horizon = start + timedelta(days=CALENDAR_DAYS - 1)
    d = Digest(start=start, end=end)
    try:
        events = parse_rm_calendar(fetch(RM_CALENDAR))
        d.source_ok = bool(events)
        if not events:
            d.warnings.append("Résistance Montréal's calendar returned no events; its page format may have changed.")
        seen = set()
        for ev in sorted(events, key=lambda e: e.start):
            key = (ev.title, ev.start)
            if key in seen or not start <= ev.start.date() <= horizon:
                continue
            seen.add(key)
            if ev.is_protest:
                d.calendar.append(ev)
            if ev.start.date() <= end:
                (d.protests if ev.is_protest else d.others).append(ev)
    except Exception as e:
        d.warnings.append(f"Could not read Résistance Montréal's calendar: {e}")
    for city, q in NEWS_QUERIES.items():
        url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
            {"q": q, "hl": "fr-CA", "gl": "CA", "ceid": "CA:fr"})
        try:
            d.news[city] = parse_news(fetch(url))
        except Exception as e:
            d.news[city] = []
            d.warnings.append(f"Google News search for {city} failed: {e}")
    return d


# ---------- rendering ----------

def fmt_day(d):
    return f"{DAYS[d.weekday()]} {d.day} {MONTHS[d.month - 1]}"


def fmt_when(ev):
    t = ev.start.strftime("%H:%M")
    return fmt_day(ev.start) + ("" if t == "00:00" else f", {t}")


def fmt_where(ev):
    detail = ev.location_detail
    if detail.startswith("(") and detail.endswith(")") and detail.count("(") == 1:
        detail = detail[1:-1]
    if detail and fold(ev.location) in fold(detail):
        detail = ""
    return ", ".join(p for p in (ev.location, detail) if p) or "location not given"


def excerpt(s, n=350):
    s = " ".join(s.split())
    return s if len(s) <= n else s[:n].rsplit(" ", 1)[0] + "…"


def subject(d):
    n = len(d.protests)
    span = f"{fmt_day(d.start)} – {fmt_day(d.end)}"
    return f"Protests, next 7 days ({n}) · {span}" if n else f"Protests, next 7 days: none listed · {span}"


CITIES = ["Montréal", "Saint-Jean-sur-Richelieu"]


def render_text(d):
    out = [subject(d), ""]
    for city in CITIES:
        evs = [e for e in d.protests if e.city == city]
        out.append(city.upper())
        out += [f"- {fmt_when(e)} | {e.title} | {fmt_where(e)}" for e in evs] or ["- nothing listed"]
        out.append("")
    out += ["-" * 60, "ANNEX", ""]
    if d.warnings:
        out += ["Warnings:"] + [f"  ! {w}" for w in d.warnings] + [""]
    for i, e in enumerate(d.protests, 1):
        out.append(f"[{i}] {e.title} ({fmt_when(e)}, {fmt_where(e)})")
        if e.description:
            out.append("    " + excerpt(e.description))
        out += [f"    {u}" for u in (e.official_url, e.source_url) if u]
        out.append("")
    if d.others:
        out.append("Other events, next 7 days, not detected as protests (check in case one is):")
        out += [f"  - {fmt_when(e)} | {e.title} | {e.source_url}" for e in d.others]
        out.append("")
    for city in CITIES:
        items = d.news.get(city) or []
        out.append(f"Recent news: {city}")
        out += [f"  - {n['title']} {n['link']}" for n in items] or ["  - nothing found"]
        out.append("")
    out.append(f"Sources: {RM_CALENDAR} (community calendar, Montreal-centric), Google News search.")
    return "\n".join(out)


def render_html(d):
    e_ = html.escape
    rows = []
    for city in CITIES:
        evs = [e for e in d.protests if e.city == city]
        rows.append(f'<h3 style="margin:18px 0 6px;font-size:15px">{e_(city)}</h3>')
        if not evs:
            rows.append('<p style="margin:0;color:#777">Nothing listed.</p>')
            continue
        rows.append('<table style="border-collapse:collapse;width:100%;font-size:14px">')
        for e in evs:
            i = d.protests.index(e) + 1
            rows.append(
                '<tr style="border-top:1px solid #e5e5e5">'
                f'<td style="padding:6px 10px 6px 0;white-space:nowrap;vertical-align:top">{e_(fmt_when(e))}</td>'
                f'<td style="padding:6px 10px 6px 0;vertical-align:top"><a href="#a{i}" style="color:#111;font-weight:600;text-decoration:none">{e_(e.title)}</a></td>'
                f'<td style="padding:6px 0;vertical-align:top;color:#444">{e_(fmt_where(e))}</td></tr>')
        rows.append("</table>")

    annex = ['<hr style="margin:28px 0 12px;border:0;border-top:1px solid #ccc">',
             '<h3 style="font-size:14px;margin:0 0 8px;color:#555">Annex</h3>']
    if d.warnings:
        annex.append('<ul style="color:#b00;font-size:13px">' + "".join(f"<li>{e_(w)}</li>" for w in d.warnings) + "</ul>")
    for i, e in enumerate(d.protests, 1):
        links = " · ".join(f'<a href="{e_(u)}">{lbl}</a>' for u, lbl in
                           ((e.official_url, "official page"), (e.source_url, "Résistance Montréal")) if u)
        annex.append(f'<p id="a{i}" style="font-size:13px;color:#333;margin:10px 0"><b>{e_(e.title)}</b> '
                     f'({e_(fmt_when(e))}, {e_(fmt_where(e))})<br>{e_(excerpt(e.description))}<br>{links}</p>')
    small = 'style="font-size:13px;color:#333;margin:4px 0 12px;padding-left:18px"'
    if d.others:
        annex.append('<p style="font-size:13px;margin:16px 0 4px"><b>Other events, next 7 days</b> '
                     '<span style="color:#777">(not detected as protests; check in case one is)</span></p>')
        annex.append(f"<ul {small}>" + "".join(
            f'<li>{e_(fmt_when(e))}: <a href="{e_(e.source_url)}">{e_(e.title)}</a></li>' for e in d.others) + "</ul>")
    for city in CITIES:
        items = d.news.get(city) or []
        annex.append(f'<p style="font-size:13px;margin:16px 0 4px"><b>Recent news: {e_(city)}</b></p>')
        annex.append(f"<ul {small}>" + ("".join(
            f'<li><a href="{e_(n["link"])}">{e_(n["title"])}</a></li>' for n in items) or "<li>Nothing found.</li>") + "</ul>")
    annex.append(f'<p style="font-size:12px;color:#777">Sources: <a href="{RM_CALENDAR}">Résistance Montréal calendar</a> '
                 "(community-run, Montreal-centric), Google News search.</p>")
    return ('<div style="font-family:system-ui,Segoe UI,sans-serif;max-width:720px;color:#111">'
            f'<h2 style="font-size:17px;margin:0 0 4px">{e_(subject(d))}</h2>' + "".join(rows) + "".join(annex) + "</div>")


# ---------- calendar feed ----------

def ics_text(s):
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def ics_fold(line):
    """Split lines longer than 75 bytes (RFC 5545), never inside a UTF-8 character."""
    b = line.encode("utf-8")
    parts, limit = [], 75
    while len(b) > limit:
        cut = limit
        while b[cut] & 0xC0 == 0x80:
            cut -= 1
        parts.append(b[:cut])
        b, limit = b[cut:], 74
    parts.append(b)
    return "\r\n ".join(x.decode("utf-8") for x in parts)


def ics_utc(dt):
    if TZ is None:  # no tz database: floating local time
        return dt.strftime("%Y%m%dT%H%M%S")
    return dt.replace(tzinfo=TZ).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def event_uid(ev):
    key = ev.source_url.rstrip("/").rsplit("/", 1)[-1] if ev.source_url else \
        hashlib.sha1(f"{ev.title}|{ev.start.isoformat()}".encode()).hexdigest()[:16]
    return f"{key}@protest-digest"


def render_ics(events):
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//protest-digest//EN", "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
        "X-WR-CALNAME:Manifs Montréal & Saint-Jean",
        "X-WR-CALDESC:" + ics_text("Upcoming protests from the Résistance Montréal calendar. Updated daily."),
        "X-WR-TIMEZONE:America/Montreal", "REFRESH-INTERVAL;VALUE=DURATION:PT6H", "X-PUBLISHED-TTL:PT6H",
    ]
    for ev in events:
        all_day = ev.start.strftime("%H:%M") == "00:00"
        desc = "\n".join(x for x in (
            f"{ev.city}" + (" (time not given)" if all_day else ""),
            excerpt(ev.description, 800) if ev.description else "",
            f"Official page: {ev.official_url}" if ev.official_url else "",
            f"Résistance Montréal: {ev.source_url}" if ev.source_url else "",
        ) if x)
        lines += ["BEGIN:VEVENT", f"UID:{event_uid(ev)}", f"DTSTAMP:{ics_utc(datetime.combine(ev.start.date(), datetime.min.time()))}"]
        if all_day:
            lines += [f"DTSTART;VALUE=DATE:{ev.start:%Y%m%d}",
                      f"DTEND;VALUE=DATE:{ev.start.date() + timedelta(days=1):%Y%m%d}"]
        else:
            lines += [f"DTSTART:{ics_utc(ev.start)}", f"DTEND:{ics_utc(ev.start + timedelta(hours=2))}"]
        lines += [f"SUMMARY:{ics_text(ev.title)}", f"LOCATION:{ics_text(fmt_where(ev))}",
                  f"DESCRIPTION:{ics_text(desc)}", f"CATEGORIES:{ics_text(ev.city)}"]
        if ev.official_url or ev.source_url:
            lines.append(f"URL:{ev.official_url or ev.source_url}")
        lines += ["TRANSP:TRANSPARENT", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(ics_fold(x) for x in lines) + "\r\n"


def render_page(d):
    stamp = datetime.now(TZ).strftime("%Y-%m-%d %H:%M") if TZ else datetime.now().strftime("%Y-%m-%d %H:%M")
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="color-scheme" content="light">'
        f"<title>Protests · Montréal & Saint-Jean</title></head>"
        '<body style="margin:0;padding:20px 16px;background:#fff">'
        + render_html(d)
        + '<div style="font-family:system-ui,Segoe UI,sans-serif;max-width:720px;font-size:12px;color:#777;margin-top:16px">'
        f'Calendar feed: <a href="protests.ics">protests.ics</a> (next {CALENDAR_DAYS} days, '
        f"subscribe to it by URL in your calendar app). Updated {stamp} Montreal time.</div></body></html>\n"
    )


def write_outputs(d, out_dir=OUT_DIR):
    out_dir.mkdir(exist_ok=True)
    (out_dir / ".nojekyll").touch()
    (out_dir / "protests.ics").write_bytes(render_ics(d.calendar).encode("utf-8"))
    (out_dir / "index.html").write_text(render_page(d), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--print", action="store_true", help="print the 7-day digest instead of writing files")
    ap.add_argument("--start", help="first day YYYY-MM-DD (default: today, Montreal time)")
    args = ap.parse_args()
    d = build(date.fromisoformat(args.start) if args.start else None)
    if args.print:
        sys.stdout.reconfigure(encoding="utf-8")
        print(render_text(d))
        return
    if not d.source_ok:
        sys.exit("not writing anything: " + "; ".join(d.warnings))
    write_outputs(d)
    print(f"{len(d.calendar)} protests in the calendar, {len(d.protests)} in the next 7 days")


if __name__ == "__main__":
    main()
