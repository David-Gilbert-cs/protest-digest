"""Offline checks of the parser and filters: python -m unittest"""

import unittest
from datetime import date

import digest

CARD = """
        one_event = {
            title: 'X @ Y',
            start: '%(start)s',
            url: 'event-content-1',
        };
        modal.innerHTML += `
            <div class="modal" id="event-content-1">
                    <h1>
                        <i class="glyphicon glyphicon-calendar"></i>
                        %(title)s
                    </h1>
                    <p>
                        <a href="https://www.openstreetmap.org/node/1">
                            <i class="glyphicon glyphicon-map-marker"></i>
                            %(place)s
                        </a>
                        <p>(métro Jarry)</p>
                    </p>
                    <p>
                        <a class="button-event-link glyphicon glyphicon-link" href="https://example.org/e">
                            Lien vers la page officielle de l'événement
                        </a>
                        <br />
                        <a class="glyphicon glyphicon-link" href="evenement/%(slug)s">
                            Lien vers l'événement sur Résistance Montréal
                        </a>
                    </p>
                    <p>%(body)s</p>
                </div>
            </div>`;
"""


def page(*cards):
    return "<script>" + "".join(CARD % c for c in cards) + "</script>"


def card(title, body="", start="2026-10-16 13:00:00", place="Parc Jarry", slug="e"):
    return {"title": title, "body": body, "start": start, "place": place, "slug": slug}


class ParseTest(unittest.TestCase):
    def test_fields(self):
        [ev] = digest.parse_rm_calendar(page(card("Manif pour le logement", "On se rassemble&nbsp;!")))
        self.assertEqual(ev.title, "Manif pour le logement")
        self.assertEqual(ev.start.isoformat(), "2026-10-16T13:00:00")
        self.assertEqual(digest.fmt_where(ev), "Parc Jarry, métro Jarry")
        self.assertEqual(ev.official_url, "https://example.org/e")
        self.assertEqual(ev.source_url, digest.RM_BASE + "evenement/e")
        self.assertEqual(ev.description, "On se rassemble !")
        self.assertTrue(ev.is_protest)

    def test_classification(self):
        evs = digest.parse_rm_calendar(page(
            card("Nuit des sans-abris - Marche de solidarité"),
            card("Libre Marché"),
            card("Vigil for Palestine"),
            card("Atelier sur le logement", "Pas une manifestation, mais on en parle."),
            card("Bouffe contre le fascisme", "Rassemblement devant l'hôtel de ville."),
            card("Piquetage", place="Hôtel de ville de Saint-Jean-sur-Richelieu"),
        ))
        got = {e.title: (e.is_protest, e.city) for e in evs}
        self.assertEqual(got["Nuit des sans-abris - Marche de solidarité"], (True, "Montréal"))
        self.assertFalse(got["Libre Marché"][0])
        self.assertTrue(got["Vigil for Palestine"][0])
        self.assertFalse(got["Atelier sur le logement"][0])
        self.assertTrue(got["Bouffe contre le fascisme"][0])
        self.assertEqual(got["Piquetage"], (True, "Saint-Jean-sur-Richelieu"))

    def test_render(self):
        evs = digest.parse_rm_calendar(page(card("Manif <b>test</b>")))
        d = digest.Digest(start=date(2026, 10, 12), end=date(2026, 10, 18), protests=evs)
        self.assertIn("Protests this week (1) · Mon 12 Oct – Sun 18 Oct", digest.render_text(d))
        self.assertIn("Fri 16 Oct, 13:00 | Manif test | Parc Jarry, métro Jarry", digest.render_text(d))
        self.assertIn("nothing listed", digest.render_text(d))
        digest.render_html(d)


if __name__ == "__main__":
    unittest.main()
