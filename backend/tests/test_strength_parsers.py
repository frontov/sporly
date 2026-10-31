import html
import json
import unittest

from app.parsers.base import (
    FbbrCalendarParser,
    FprCalendarParser,
    NapCalendarParser,
    NbcEventsParser,
    RfwfCalendarParser,
    SourceConfig,
    SourceFieldMap,
    SpswProgramParser,
    WpcCalendarParser,
    WrpfCalendarParser,
)
from app.services.catalog import CatalogService


def make_parser(parser_class, name: str = "Тест", parser_type: str = "test"):
    return parser_class(
        SourceConfig(
            name=name,
            base_url="https://example.com",
            listing_urls=["https://example.com/calendar"],
            selectors=SourceFieldMap(
                item="article", title="h1", link="a[href]"
            ),
            parser_type=parser_type,
        )
    )


class StrengthCategoryTest(unittest.TestCase):
    def test_normalizes_strength_disciplines(self) -> None:
        for value in (
            "Пауэрлифтинг",
            "Тяжелая атлетика",
            "Тяжёлая атлетика",
            "Бодибилдинг",
            "Кроссфит",
            "Гиревой спорт",
            "Стронгмен",
            "Силовое двоеборье",
            "Жим лежа",
        ):
            with self.subTest(value=value):
                self.assertEqual(
                    CatalogService._normalize_category(None, value),
                    "Силовые виды",
                )

    def test_does_not_confuse_light_athletics_with_weightlifting(self) -> None:
        self.assertEqual(
            CatalogService._normalize_category(None, "Легкая атлетика"),
            "Разное",
        )


class FprCalendarTest(unittest.TestCase):
    HTML = """
    <html><body>
    <table><tr><td>2026 год</td><td>КАЛЕНДАРЬ</td></tr></table>
    <table>
      <tr><td>2026 год</td><td>КАЛЕНДАРЬ</td></tr>
      <tr><td>1</td><td>2</td><td>3</td><td>Наименование</td><td>4</td><td>5</td><td>6</td><td>7</td><td>8</td><td>9</td></tr>
      <tr><td>1</td><td>ЕКП</td><td>ПФО</td><td>Первенство Уральского ФО</td><td>14-18</td><td>ЖЭ</td><td>03 – 11 января</td><td>Нижний Тагил</td><td>заявки</td><td>бланк</td></tr>
      <tr><td>2</td><td>ЕКП</td><td>ЧФО</td><td>Чемпионат Уральского ФО</td><td>14+</td><td>ЖЭ</td><td>24 января – 01 февраля</td><td>Тюмень</td><td>заявки</td><td>бланк</td></tr>
      <tr><td>3</td><td>ЕКП</td><td>ПФО</td><td>Первенство Сибирского ФО</td><td>14-18</td><td>ЖК</td><td>17 – 25 января</td><td>Омск</td><td>заявки</td><td>бланк</td></tr>
      <tr><td>4</td><td>ЕКП</td><td>ПФО</td><td>Первенство Приволжского ФО</td><td>14-18</td><td>ЖК</td><td>01 – 09 февраля</td><td>Ижевск</td><td>заявки</td><td>бланк</td></tr>
      <tr><td>5</td><td>ЕКП</td><td>ПФО</td><td>Первенство Южного ФО</td><td>14-18</td><td>ЖК</td><td>02 – 08 марта</td><td>Ростов-на-Дону</td><td>заявки</td><td>бланк</td></tr>
    </table>
    </body></html>
    """

    def test_parses_year_table_and_russian_date_ranges(self) -> None:
        events = make_parser(FprCalendarParser).parse(
            self.HTML, "https://fpr-info.ru/kalendar.htm"
        )

        self.assertEqual(len(events), 5)
        self.assertEqual(events[0].starts_at, "2026-01-03T00:00:00")
        self.assertEqual(events[0].city, "Нижний Тагил")
        self.assertEqual(events[1].starts_at, "2026-01-24T00:00:00")
        self.assertEqual(events[0].category, "Силовые виды")
        self.assertEqual(
            str(events[0].source_url), "https://fpr-info.ru/kalendar.htm"
        )
        self.assertNotIn("#", str(events[0].source_url))
        self.assertEqual(len({event.id for event in events}), len(events))

    def test_decodes_windows_1251_calendar(self) -> None:
        parser = make_parser(FprCalendarParser)
        decoded = parser._decode(self.HTML.encode("cp1251"))

        self.assertIn("Первенство Уральского ФО", decoded)


class RfwfCalendarTest(unittest.TestCase):
    def test_parses_embedded_json_and_location(self) -> None:
        payload = [
            {
                "id": 1,
                "name": "Кубок России",
                "url": "/competitions/kubok_rossii/",
                "dateFrom": 1776556800,
                "dateTo": 1777161600,
                "event": "Кубок России",
                "category": "Взрослые",
                "country": "г. Калач, Воронежская область",
                "status": "future",
                "cancelled": 0,
            }
        ]
        page = f"<script>window.calendar = {html.escape(json.dumps(payload, ensure_ascii=False))};</script>"

        events = make_parser(RfwfCalendarParser).parse(
            page, "https://rfwf.ru/competitions/calendar"
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].title, "Кубок России")
        self.assertEqual(events[0].starts_at, "2026-04-19T00:00:00")
        self.assertEqual(events[0].city, "Калач")
        self.assertEqual(events[0].region, "Воронежская область")


class NapCalendarTest(unittest.TestCase):
    def test_parses_month_section_and_location(self) -> None:
        page = """
        <section class="cal__m" data-m="2026-11">
          <article class="trow">
            <span class="dt"><b>7-8</b><i>ноя</i></span>
            <div class="trow__body">
              <h3 class="trow__t"><a href="/calendar/2173/">АБСОЛЮТНАЯ СИЛА - VII</a></h3>
              <p class="trow__w">Волгодонск, Ростовская область</p>
            </div>
          </article>
        </section>
        """

        events = make_parser(NapCalendarParser).parse(
            page, "https://powerlifting-russia.ru/calendar/"
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].starts_at, "2026-11-07T00:00:00")
        self.assertEqual(events[0].city, "Волгодонск")
        self.assertEqual(events[0].region, "Ростовская область")
        self.assertEqual(
            events[0].source_url,
            "https://powerlifting-russia.ru/calendar/2173/",
        )


class WpcCalendarTest(unittest.TestCase):
    def test_parses_listing_card(self) -> None:
        page = """
        <div class="artlist_item">
          <div class="artlist_date">26.12.2026</div>
          <h3 class="artlist_title">Чемпионат СНГ WPSO/WPC/WAO 2026</h3>
          <div class="artlist_content">Наименование события</div>
          <a href="/calendar/event.html" class="artlist_more">подробнее</a>
        </div>
        """

        events = make_parser(WpcCalendarParser).parse(
            page, "http://www.wpc-wpo.ru/calendar/?y=2026"
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].starts_at, "2026-12-26T00:00:00")
        self.assertEqual(events[0].title, "Чемпионат СНГ WPSO/WPC/WAO 2026")


class WrpfCalendarTest(unittest.TestCase):
    def test_keeps_commas_in_title_and_reads_cross_month_range(self) -> None:
        page = """
        <article class="item-page">
          <ol><li><p>Всероссийский турнир «World Class» по пауэрлифтингу, силовому двоеборью
          и жиму лежа, Россия / Москва, 31.01–01.02.2026 (присвоение до PRO включительно)</p></li></ol>
        </article>
        """

        events = make_parser(WrpfCalendarParser).parse(
            page,
            "https://russia-powerlifting.ru/kalendar/kalendar-sorevnovanij-2026",
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].starts_at, "2026-01-31T00:00:00")
        self.assertEqual(events[0].city, "Москва")
        self.assertEqual(
            str(events[0].source_url),
            "https://russia-powerlifting.ru/kalendar/kalendar-sorevnovanij-2026",
        )
        self.assertNotIn("#", str(events[0].source_url))
        self.assertEqual(
            events[0].title,
            "Всероссийский турнир «World Class» по пауэрлифтингу, силовому двоеборью и жиму лежа",
        )

    def test_events_from_one_calendar_page_have_unique_ids(self) -> None:
        page = """
        <article class="item-page">
          <ol>
            <li><p>Первый турнир по пауэрлифтингу, Россия / Москва, 10.01.2027</p></li>
            <li><p>Второй турнир по пауэрлифтингу, Россия / Москва, 11.01.2027</p></li>
          </ol>
        </article>
        """

        events = make_parser(WrpfCalendarParser).parse(
            page,
            "https://russia-powerlifting.ru/kalendar/kalendar-sorevnovanij-2027",
        )

        self.assertEqual(len(events), 2)
        self.assertEqual(len({event.id for event in events}), 2)
        self.assertEqual(
            {str(event.source_url) for event in events},
            {"https://russia-powerlifting.ru/kalendar/kalendar-sorevnovanij-2027"},
        )

    def test_prefers_region_hint_over_city_chunk(self) -> None:
        page = """
        <article class="item-page">
          <ol><li><p>Открытый турнир «Натухаевская» по пауэрлифтингу,
          Россия / Краснодарский край, Новороссийск, Натухаевская,
          10-12.01.2027</p></li></ol>
        </article>
        """

        events = make_parser(WrpfCalendarParser).parse(
            page,
            "https://russia-powerlifting.ru/kalendar/kalendar-sorevnovanij-2027",
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].city, "Натухаевская")
        self.assertEqual(events[0].region, "Краснодарский край")

    def test_does_not_treat_venue_as_region(self) -> None:
        parser = make_parser(WrpfCalendarParser)
        self.assertEqual(
            parser._strength_location("Новороссийск, Фитнес клуб «FitZone»"),
            ("Новороссийск", None),
        )


class FbbrCalendarTest(unittest.TestCase):
    def test_cleans_prefix_and_reads_event_date_from_excerpt(self) -> None:
        page = """
        <article>
          <header><h2 class="entry-title"><a href="https://fbbr.org/2026/23992">Положение: Кубок Кузбасса — 2026</a></h2></header>
          <div class="entry-content"><p>Положение Кубок Кузбасса 6.12.2026</p></div>
        </article>
        """

        events = make_parser(FbbrCalendarParser).parse(
            page, "https://fbbr.org/category/competitions/anons"
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].title, "Кубок Кузбасса — 2026")
        self.assertEqual(events[0].starts_at, "2026-12-06T00:00:00")


class NbcEventsTest(unittest.TestCase):
    def test_parses_date_location_and_venue(self) -> None:
        page = """
        <div class="event-block">
          <div class="event-image"><img src="/upload/image.png"></div>
          <div class="event-description-left">
            <h3>15 Ноября 2026 г.</h3>
            <span><a href="/events/nbc-battle-4/">NBC BATTLE 4</a></span>
            <div class="event-location">Москва, ул. Электродная, д. 2, ст. 32</div>
          </div>
        </div>
        """

        events = make_parser(NbcEventsParser).parse(
            page, "https://nbcpro.ru/events/"
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].starts_at, "2026-11-15T00:00:00")
        self.assertEqual(events[0].city, "Москва")
        self.assertEqual(events[0].venue, "ул. Электродная, д. 2, ст. 32")
        self.assertEqual(events[0].category, "Силовые виды")


class SpswProgramTest(unittest.TestCase):
    def test_builds_single_festival_event_for_the_programme_year(self) -> None:
        page = """
        <html><head><meta property="og:image" content="https://spsw.ru/poster.jpg"></head>
        <body>
          <h1>Программа Siberian Power Show 2026</h1>
          <div class="t056">
            <div class="t056__title">Кристалл Арена</div>
            <div class="t056__descr">ул. Партизана Железняка 42 – 27-29 марта с 10:00</div>
          </div>
          <div class="t056">
            <div class="t056__title">МВДЦ Сибирь</div>
            <div class="t056__descr">ул. Авиаторов 19 – 28-29 марта с 10:00</div>
          </div>
        </body></html>
        """

        events = make_parser(SpswProgramParser).parse(
            page, "https://spsw.ru/program"
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].title, "Siberian Power Show 2026")
        self.assertEqual(events[0].starts_at, "2026-03-27T00:00:00")
        self.assertEqual(events[0].city, "Красноярск")
        self.assertEqual(events[0].venue, "Кристалл Арена, МВДЦ Сибирь")
        self.assertEqual(events[0].category, "Силовые виды")


if __name__ == "__main__":
    unittest.main()
