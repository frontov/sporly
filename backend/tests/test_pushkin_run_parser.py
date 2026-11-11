import unittest
from datetime import datetime

from app.parsers.base import PushkinRunParser, SourceConfig, SourceFieldMap


def _text(value: str, font_size: int) -> str:
    return (
        '<div class="t396__elem" data-elem-type="text" '
        f'data-field-fontsize-value="{font_size}">'
        f'<div class="tn-atom">{value}</div></div>'
    )


def _button(label: str, href: str | None = None) -> str:
    link = f'<a href="{href}">{label}</a>' if href else label
    return (
        '<div class="t396__elem" data-elem-type="button">'
        f'<div class="tn-atom">{link}</div></div>'
    )


def _card(
    rec_id: str,
    *,
    title: str,
    month: str,
    day: str | None = None,
    distances: str | None = None,
    description: str | None = None,
    detail: str | None = None,
    registration: str | None = None,
    detail_label: str = "ПОДРОБНЕЕ",
    registration_label: str = "РЕГИСТРАЦИЯ",
    mobile: bool = False,
) -> str:
    elements = []
    if distances:
        elements.append(_text(f"Дистанции: {distances}", 18))
    elements.append(_text(title, 40))
    if day:
        elements.append(_text(day, 40))
    elements.append(_text(month, 14))
    if description:
        elements.append(_text(description, 15))
    if detail is not None:
        elements.append(_button(detail_label, detail))
    if registration is not None:
        elements.append(_button(registration_label, registration))
    elif registration_label:
        elements.append(_button(registration_label))
    screen_class = "t-screenmax-980px" if mobile else "t-screenmin-980px"
    return (
        f'<div class="t-rec {screen_class}" data-record-type="396" id="{rec_id}">'
        '<div class="t396__artboard">'
        + "".join(elements)
        + "</div></div>"
    )


def _page(*cards: str) -> str:
    return f"<html><body>{''.join(cards)}</body></html>"


class PushkinRunParserTest(unittest.TestCase):
    def setUp(self) -> None:
        config = SourceConfig(
            name="PushkinRun",
            base_url="https://pushkin-run.ru",
            listing_urls=["https://pushkin-run.ru/"],
            selectors=SourceFieldMap(
                item='div.t-rec[data-record-type="396"]',
                title='.t396__elem[data-elem-type="text"]',
                link="a[href]",
            ),
            parser_type="pushkin_run",
        )
        self.parser = PushkinRunParser(config)
        self.now = datetime(2026, 11, 11)

    def parse(self, html: str):
        return self.parser.parse(
            html, "https://pushkin-run.ru/", now=self.now
        )

    def test_parses_card_fields(self) -> None:
        html = _page(
            _card(
                "rec1",
                title="9-Й Царскосельский Марафон",
                month="мая",
                day="10",
                distances="3 км / 11 км / 21,1 км / 42,2 км, детский забег",
                description="Уникальная видовая трасса.",
                detail="https://pushkin-run.ru/tsarskoselsky_marathon_2027",
                registration="https://reg.russiarunning.com/event/TsarskoselskiyMarafon2027",
            )
        )

        events = self.parse(html)

        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event.title, "9-Й Царскосельский Марафон")
        self.assertEqual(event.starts_at, "2027-05-10T00:00:00")
        self.assertEqual(event.date_text, "10 мая 2027")
        self.assertEqual(
            event.distance_summary,
            "3 км • 11 км • 21.1 км • 42.2 км",
        )
        self.assertEqual(event.description, "Уникальная видовая трасса.")
        self.assertEqual(event.city, "Санкт-Петербург")
        self.assertEqual(event.region, "Санкт-Петербург")
        self.assertEqual(event.category, "Бег")
        self.assertTrue(event.kids_available)
        self.assertEqual(event.registration_status, "open")
        self.assertEqual(
            str(event.source_url),
            "https://pushkin-run.ru/tsarskoselsky_marathon_2027",
        )

    def test_rolls_month_only_cards_to_next_year(self) -> None:
        html = _page(
            _card("rec1", title="Пулково — Пушкин", month="январь"),
            _card("rec2", title="Павловский забег", month="октябрь"),
        )

        events = self.parse(html)

        self.assertEqual(
            [(event.date_text, event.starts_at) for event in events],
            [
                ("январь 2027", None),
                ("октябрь 2027", None),
            ],
        )

    def test_merges_desktop_and_mobile_copies(self) -> None:
        html = _page(
            _card("rec1", title="Арена Марафон", month="октябрь"),
            _card(
                "rec2",
                title="Арена Марафон",
                month="октябрь",
                day="24",
                mobile=True,
            ),
        )

        events = self.parse(html)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].starts_at, "2027-10-24T00:00:00")
        self.assertEqual(events[0].date_text, "24 октября 2027")

    def test_skips_cards_with_past_explicit_year(self) -> None:
        html = _page(
            _card(
                "rec1",
                title="Детский забег «АРЕНА МАРАФОН 2026»",
                month="октябрь",
            ),
            _card("rec2", title="Павловский забег", month="октябрь"),
        )

        events = self.parse(html)

        self.assertEqual(
            [event.title for event in events], ["Павловский забег"]
        )

    def test_ignores_cards_without_month(self) -> None:
        html = _page(
            _card(
                "rec1",
                title="ВОСКРЕСНЫЕ ПРОБЕЖКИ",
                month="",
                description="Каждое воскресенье.",
            ),
            '<div class="t-rec t-screenmin-980px" data-record-type="396">'
            '<div class="t396__artboard">'
            + _text("ДЕТСКИЕ ЗАБЕГИ", 40)
            + "</div></div>",
        )

        self.assertEqual(self.parse(html), [])

    def test_registration_button_states(self) -> None:
        html = _page(
            _card(
                "rec1",
                title="ЭКИДЕН 42,195/6",
                month="июня",
                day="13",
                detail="https://ekiden.run/",
                registration_label="РЕГИСТРАЦИЯ (скоро)",
            ),
            _card(
                "rec2",
                title="Ночной забег",
                month="июля",
                day="24",
                registration_label="РЕГИСТРАЦИЯ (готовится)",
            ),
        )

        events = self.parse(html)

        self.assertEqual(events[0].registration_status, "upcoming")
        # With no detail page the registration/calendar anchor is used.
        self.assertEqual(str(events[1].source_url), "https://pushkin-run.ru/#event-2")

    def test_preserves_relay_distance_chain(self) -> None:
        html = _page(
            _card(
                "rec1",
                title="ЭКИДЕН 42,195/6",
                month="июня",
                day="13",
                distances="5км-10км-5км-10км-5км-7,195 км",
            )
        )

        events = self.parse(html)

        self.assertEqual(
            events[0].distance_summary,
            "5км-10км-5км-10км-5км-7,195 км",
        )


if __name__ == "__main__":
    unittest.main()
