import unittest

from bs4 import BeautifulSoup

from app.parsers.base import (
    CssDirectoryParser,
    IronStarParser,
    OrgeoParser,
    OTimeCalendarParser,
    SourceConfig,
    SourceFieldMap,
)


def _config(name: str = "Test", base_url: str = "https://example.com") -> SourceConfig:
    return SourceConfig(
        name=name,
        base_url=base_url,
        listing_urls=[],
        selectors=SourceFieldMap(item="x", title="x", link="x"),
    )


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


class RegistrationPageDetectionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = CssDirectoryParser(_config())

    def test_account_menu_link_is_not_a_status(self) -> None:
        soup = _soup(
            "<nav><a href='/user/registration'>Регистрация</a>"
            "<a href='/login'>Войти</a></nav><p>Инфо</p>"
        )

        self.assertEqual(self.parser._extract_registration_from_page(soup), (None, None))

    def test_claim_link_means_registration_is_open(self) -> None:
        soup = _soup(
            "<nav><a href='/user/registration'>Регистрация</a></nav>"
            "<a href='/claim/create/event_id/42'>Подать заявку</a>"
        )

        self.assertEqual(
            self.parser._extract_registration_from_page(soup)[0], "open"
        )

    def test_registration_closed_marker(self) -> None:
        soup = _soup("<p>Регистрация закрыта</p>")

        self.assertEqual(
            self.parser._extract_registration_from_page(soup)[0], "closed"
        )

    def test_registration_upcoming_marker(self) -> None:
        soup = _soup("<p>Регистрация откроется 1 декабря 2026</p>")

        self.assertEqual(
            self.parser._extract_registration_from_page(soup)[0], "upcoming"
        )

    def test_open_marker_and_deadline(self) -> None:
        soup = _soup(
            "<p>Регистрация открыта до 15 января 2027; нужны документы.</p>"
        )

        status, deadline = self.parser._extract_registration_from_page(soup)
        self.assertEqual(status, "open")
        self.assertEqual(deadline, "до 15 января 2027")

    def test_register_button_means_open(self) -> None:
        soup = _soup(
            "<a href='/registration/race-2027/'>Зарегистрироваться</a>"
        )

        self.assertEqual(
            self.parser._extract_registration_from_page(soup)[0], "open"
        )


class IronStarRegistrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = IronStarParser(
            _config("IRONSTAR", "https://iron-star.com")
        )

    def test_open_registration_block(self) -> None:
        soup = _soup(
            '<div class="event-card-buttons-reg">'
            "<h3>до конца регистрации осталось 9 дней</h3>"
            "<a class='btn'>Регистрация</a></div>"
        )

        status, deadline = self.parser._extract_ironstar_registration(soup)

        self.assertEqual(status, "open")
        self.assertTrue(deadline and deadline.startswith("до "))

    def test_upcoming_registration_block(self) -> None:
        soup = _soup(
            '<div class="event-card-buttons-reg">'
            "<h3>Регистрация скоро откроется</h3></div>"
        )

        self.assertEqual(
            self.parser._extract_ironstar_registration(soup)[0], "upcoming"
        )

    def test_closed_registration_block(self) -> None:
        soup = _soup(
            '<div class="event-card-buttons-reg">'
            "<h3>Регистрация закрыта</h3></div>"
        )

        self.assertEqual(
            self.parser._extract_ironstar_registration(soup)[0], "closed"
        )


class OTimeRegistrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = OTimeCalendarParser(
            _config("O-Time", "https://reg.o-time.ru")
        )

    def test_entry_button_marks_registration_open(self) -> None:
        soup = _soup(
            '<a href="https://reg.o-time.ru/step1.php?ev=0&event=26486">'
            "Register</a>"
        )

        self.assertEqual(
            self.parser._extract_otime_registration_details(soup)[0], "open"
        )

    def test_page_without_entry_button_has_no_status(self) -> None:
        soup = _soup("<p>Registration Total participants: 0</p>")

        self.assertEqual(
            self.parser._extract_otime_registration_details(soup), (None, None)
        )


class OrgeoRegistrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = OrgeoParser(_config("Orgeo", "https://orgeo.ru"))

    def test_claim_link_marks_event_open(self) -> None:
        soup = _soup(
            "<nav><a href='/user/registration'>Регистрация</a></nav>"
            "<a href='/claim/create/event_id/56414'>Подать заявку</a>"
            "<p>Свободных мест: 2 из 15</p>"
        )

        self.assertEqual(
            self.parser._extract_orgeo_registration_details(soup)[0], "open"
        )

    def test_info_only_event_has_no_status(self) -> None:
        soup = _soup(
            "<nav><a href='/user/registration'>Регистрация</a></nav>"
            "<p>Инфо Обсуждение Страховка Место проведения</p>"
        )

        self.assertEqual(
            self.parser._extract_orgeo_registration_details(soup), (None, None)
        )

    def test_full_event_is_closed(self) -> None:
        soup = _soup(
            "<p>Регистрация закрыта 11.11.2026 12:00</p>"
            "<p>Свободных мест: 0 из 600</p>"
        )

        status, deadline = self.parser._extract_orgeo_registration_details(soup)
        self.assertEqual(status, "closed")
        self.assertEqual(deadline, "до 11.11.2026 12:00")


if __name__ == "__main__":
    unittest.main()
