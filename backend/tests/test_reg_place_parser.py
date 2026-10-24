import unittest

from app.parsers.base import RegPlaceParser, SourceConfig, SourceFieldMap

DETAIL_HTML = """
<html>
  <head>
    <meta name="description" content="Осенний трейл 24 октября, Спас-Каменка" />
    <meta property="og:image" content="https://reg.place/uploads/image/og.jpg" />
  </head>
  <body>
    <section class="event-page__hero">
      <div class="event-page__intro">
        <div class="event-page__date">24.10.2026</div>
        <h1 class="event-page__title">Spas-Kamenka Gryadka Trail 2026</h1>
        <div class="event-page__location">
          <i class="fa-map-marker-alt fal"></i>
          <span>Спас-Каменка, Московская обл, г Дмитров, деревня Спас-Каменка</span>
        </div>
        <p class="event-page__lead">Осенний яркий трейл в Подмосковье</p>
        <div class="event-page__actions">
          <a class="btn btn-block btn-primary btn-cta" href="/events/spaskamenka2026/registration">
            Зарегистрироваться
          </a>
        </div>
        <div class="event-page__registration-note">
          <span class="mr-1">Регистрация до</span>
          <span class="text-nowrap">28 октября 2026</span>
        </div>
      </div>
    </section>
    <main class="event-page__main">
      <section class="event-page__section" id="races">
        <div class="event-page__section-heading">
          <h2 class="event-page__section-title">Дисциплины<span class="event-page__count"> (5)</span></h2>
        </div>
        <article class="race-card">
          <h3 class="race-card__title">LONG</h3>
          <ul class="race-price__variants">
            <li class="race-price__variant race-price__variant--crossed-out">
              Первая цена<span class="race-price__amount text-nowrap"> – 4 200 ₽</span>
            </li>
            <li class="race-price__variant">
              Финальная цена<span class="race-price__amount text-nowrap"> – 5 052,63 ₽</span>
            </li>
          </ul>
        </article>
        <article class="race-card">
          <h3 class="race-card__title">KIDS</h3>
          <ul class="race-price__variants">
            <li class="race-price__variant">Финальная цена<span class="race-price__amount text-nowrap"> – 2 500 ₽</span></li>
          </ul>
        </article>
      </section>
      <section class="event-page__section" id="about">
        <div class="event-description"><p>Описание старта</p></div>
      </section>
      <section class="event-page__section" id="place">
        <event-location-map address="Московская обл, г Дмитров, деревня Спас-Каменка"></event-location-map>
      </section>
    </main>
    <section class="event-page__section event-page__organiser-card">
      <h2 class="event-page__organiser-name">ИП Иванов</h2>
    </section>
  </body>
</html>
"""

LEGACY_DETAIL_HTML = """
<html>
  <body>
    <h1>Старый старт</h1>
    <h2>5 октября 2026</h2>
    <p class="lead text-muted">Москва</p>
    <a class="btn btn-block btn-cta" href="/registration">Регистрация закрыта</a>
  </body>
</html>
"""

LISTING_HTML = """
<div class="pager">
  <ul class="pagination">
    <li class="page-item active"><a class="page-link" href="/events">1</a></li>
    <li class="page-item"><a class="page-link" href="/events?page=2">2</a></li>
    <li class="page-item"><a class="page-link" href="/events?page=3">3</a></li>
    <li class="page-item page gap disabled"><span class="page-link">&hellip;</span></li>
    <li class="page-item"><a class="page-link" href="/events?page=5">5</a></li>
    <li class="page-item last next"><a class="page-link" href="/events?page=6">6</a></li>
  </ul>
</div>
"""


def make_parser(max_pages: int = 10) -> RegPlaceParser:
    return RegPlaceParser(
        SourceConfig(
            name="REGPLACE",
            base_url="https://reg.place",
            listing_urls=["https://reg.place/events"],
            selectors=SourceFieldMap(item=".b-event-card", title="h3 a", link="h3 a"),
            parser_type="reg_place",
            pagination_selector=".pagination .page-link",
            max_pages=max_pages,
        )
    )


class RegPlaceDetailParsingTest(unittest.TestCase):
    def test_reads_date_from_hero_not_section_heading(self) -> None:
        event = make_parser()._parse_regplace_detail_page(
            DETAIL_HTML, "https://reg.place/events/spaskamenka2026"
        )

        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual(event.date_text, "24.10.2026")
        self.assertEqual(event.starts_at, "2026-10-24T00:00:00")

    def test_extracts_hero_location_registration_and_price(self) -> None:
        event = make_parser()._parse_regplace_detail_page(
            DETAIL_HTML, "https://reg.place/events/spaskamenka2026"
        )

        assert event is not None
        self.assertEqual(event.city, "Спас-Каменка")
        self.assertEqual(event.region, "Московская область")
        self.assertEqual(event.registration_status, "open")
        self.assertEqual(event.registration_deadline, "до 28 октября 2026")
        self.assertEqual(event.organizer_name, "ИП Иванов")
        self.assertEqual(event.price_from, "от 2500 ₽")
        self.assertEqual(
            event.image_url, "https://reg.place/uploads/image/og.jpg"
        )

    def test_normalizes_date_range_to_first_day(self) -> None:
        parser = make_parser()

        self.assertEqual(
            parser._normalize_regplace_numeric_date("30.10–01.11.2026"),
            "30.10.2026",
        )
        self.assertEqual(
            parser._normalize_regplace_numeric_date("04.11.2026"), "04.11.2026"
        )
        self.assertIsNone(parser._normalize_regplace_numeric_date("Дисциплины (5)"))

    def test_keeps_legacy_h2_date_markup(self) -> None:
        event = make_parser()._parse_regplace_detail_page(
            LEGACY_DETAIL_HTML, "https://reg.place/events/legacy"
        )

        assert event is not None
        self.assertEqual(event.starts_at, "2026-10-05T00:00:00")
        self.assertEqual(event.registration_status, "closed")


class RegPlacePaginationTest(unittest.TestCase):
    def test_follows_every_page_behind_ellipsis_gap(self) -> None:
        urls = make_parser().extract_pagination_urls(
            LISTING_HTML, "https://reg.place/events"
        )

        self.assertEqual(
            urls,
            [
                "https://reg.place/events?page=2",
                "https://reg.place/events?page=3",
                "https://reg.place/events?page=4",
                "https://reg.place/events?page=5",
                "https://reg.place/events?page=6",
            ],
        )


if __name__ == "__main__":
    unittest.main()
