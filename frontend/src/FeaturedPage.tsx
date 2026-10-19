import { useState } from "react";
import { EventCard } from "./components/EventCard";
import { useFeaturedEvents } from "./hooks/useFeaturedEvents";
import { navigateLinkProps, useRoute } from "./hooks/useRoute";

const FOOTER_CONTACTS = {
  email: "fronteno@yandex.ru",
  telegram: "https://t.me/fronteno"
};

export const FeaturedPage = () => {
  const { navigate } = useRoute();
  const [page, setPage] = useState(1);
  const { data, loading, error } = useFeaturedEvents(page);

  const navigateToPage = (nextPage: number) => {
    setPage(nextPage);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  return (
    <div className="page-shell">
      <header className="hero">
        <div className="hero__top">
          <div className="hero__brand">
            <img className="hero__logo" src="/logo-mark.svg" alt="" aria-hidden="true" />
            <h1>sporly</h1>
          </div>
          <nav className="hero__nav">
            <a className="hero__nav-link" {...navigateLinkProps("/", navigate)}>
              На главную
            </a>
            <a className="hero__nav-link" {...navigateLinkProps("/calendar", navigate)}>
              Календарь
            </a>
          </nav>
        </div>
        <p className="hero__brand-text">рекомендованные старты</p>
      </header>

      <section className="featured-intro">
        <h2>Рекомендовано Sporly</h2>
        <p>
          Старты, которые мы отмечаем как особенно интересные. Они выделены
          звёздочкой и поднимаются в начало общей выдачи.
        </p>
      </section>

      {error ? (
        <section className="empty-state empty-state--error">
          <h2>Не удалось загрузить рекомендации</h2>
          <p>Попробуйте обновить страницу чуть позже.</p>
        </section>
      ) : null}

      {loading ? (
        <section className="loading-state" aria-live="polite" aria-busy="true">
          <div className="loading-state__mark">
            <img src="/logo-mark.svg" alt="" aria-hidden="true" />
          </div>
          <div className="loading-state__copy">
            <h2>Собираем рекомендации</h2>
            <p>Ищем отмеченные старты</p>
          </div>
        </section>
      ) : null}

      {!loading && !error && data.items.length === 0 ? (
        <section className="empty-state">
          <h2>Пока нет рекомендованных стартов</h2>
          <p>Загляните позже — мы регулярно отмечаем интересные события.</p>
        </section>
      ) : null}

      {!loading && !error && data.items.length > 0 ? (
        <>
          <div className="results-summary" aria-live="polite">
            Рекомендованных стартов: {data.total}
          </div>
          <section className="events-grid">
            {data.items.map((event) => (
              <EventCard key={event.id} event={event} showDetails />
            ))}
          </section>
        </>
      ) : null}

      {!loading && !error && data.total_pages > 1 ? (
        <nav className="pagination" aria-label="Пагинация рекомендованных событий">
          <button
            type="button"
            onClick={() => navigateToPage(Math.max(page - 1, 1))}
            disabled={data.page <= 1}
          >
            Назад
          </button>
          <span>
            Страница {data.page} из {data.total_pages}
          </span>
          <button
            type="button"
            onClick={() => navigateToPage(Math.min(page + 1, data.total_pages))}
            disabled={data.page >= data.total_pages}
          >
            Вперёд
          </button>
        </nav>
      ) : null}

      <footer className="site-footer">
        <span className="site-footer__brand">sporly</span>
        <span className="site-footer__item">
          помогаем искать спортивные события с 2026 года
        </span>
        <a className="site-footer__link" href={`mailto:${FOOTER_CONTACTS.email}`}>
          почта
        </a>
        <a
          className="site-footer__link"
          href={FOOTER_CONTACTS.telegram}
          target="_blank"
          rel="noreferrer"
        >
          telegram
        </a>
      </footer>
    </div>
  );
};
