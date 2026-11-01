import unittest

from app.parsers.base import GryadkaCampsParser, SourceConfig, SourceFieldMap


CAMP_HTML = """
<html>
  <body>
    <div class="t774">
      <div class="t-section__descr">Кэмпы от gryadka.club</div>
      <div class="t774__col">
        <meta itemprop="image" content="https://example.com/vkatka.jpg">
        <div class="t-card__title"><a href="/vkatka">Вкатка 2026</a></div>
        <div class="t-card__descr">
          28.11-06.12.2026, Ханты-Мансийск
          Вкатка: открытие лыжного сезона.
        </div>
      </div>
      <div class="t774__col">
        <meta itemprop="image" content="https://example.com/altai.jpg">
        <div class="t-card__title"><a href="/murmansk27">Трейловый кэмп на Алтае</a></div>
        <div class="t-card__descr">
          19-27 июня 2027 г, п.Тюнгур, р.Алтай
          Беговой трейловый кэмп.
        </div>
      </div>
      <div class="t774__col">
        <div class="t-card__title"><a href="/race">Наши старты в 2026 году</a></div>
        <div class="t-card__descr">Новости на странице соревнований.</div>
      </div>
    </div>
  </body>
</html>
"""


class GryadkaCampsParserTest(unittest.TestCase):
    def setUp(self) -> None:
        config = SourceConfig(
            name="Gryadka",
            base_url="https://gryadka.club",
            listing_urls=["https://gryadka.club"],
            selectors=SourceFieldMap(
                item=".t774__col",
                title=".t-card__title a",
                link=".t-card__title a",
            ),
        )
        self.parser = GryadkaCampsParser(config)

    def test_parses_only_camp_cards(self) -> None:
        events = self.parser.parse(CAMP_HTML, "https://gryadka.club")

        self.assertEqual([event.title for event in events], [
            "Вкатка 2026",
            "Трейловый кэмп на Алтае",
        ])

        vkatka, altai = events
        self.assertEqual(vkatka.category, "Лыжи")
        self.assertEqual(vkatka.city, "Ханты-Мансийск")
        self.assertEqual(vkatka.starts_at, "2026-11-28T00:00:00")
        self.assertEqual(vkatka.source_url, "https://gryadka.club/vkatka")
        self.assertEqual(vkatka.image_url, "https://example.com/vkatka.jpg")

        self.assertEqual(altai.category, "Бег")
        self.assertEqual(altai.city, "Тюнгур")
        self.assertEqual(altai.starts_at, "2027-06-19T00:00:00")
        self.assertEqual(altai.source_url, "https://gryadka.club/altai27")

    def test_parses_numeric_date_ranges(self) -> None:
        starts_at, date_text = self.parser._parse_camp_dates(
            "31.12.2026 - 07.01.2027, Кировская обл."
        )
        self.assertEqual(starts_at, "2026-12-31T00:00:00")
        self.assertIn("31.12.2026", date_text or "")
        self.assertIn("07.01.2027", date_text or "")

        starts_at, date_text = self.parser._parse_camp_dates(
            "28.11-06.12.2026, Ханты-Мансийск"
        )
        self.assertEqual(starts_at, "2026-11-28T00:00:00")
        self.assertIn("28.11.2026", date_text or "")


if __name__ == "__main__":
    unittest.main()
