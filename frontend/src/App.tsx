import { useEffect, useState } from "react";
import { normalizeCategoryLabel } from "./categories";
import { EventCard } from "./components/EventCard";
import { FiltersPanel } from "./components/FiltersPanel";
import { useEvents } from "./hooks/useEvents";
import { FiltersState } from "./types/events";

const initialFilters: FiltersState = {
  q: "",
  cities: [],
  categories: [],
  dateFrom: "",
  dateTo: "",
  sortBy: "date_asc",
  includePast: false
};

const FILTERS_STORAGE_KEY = "sporly.filters";
const isPureRegionOption = (value: string) => {
  const normalized = value.trim();
  if (!normalized || normalized.includes(",") || normalized.includes(" и ")) {
    return false;
  }

  return (
    /(область|край|республика|автономный округ)$/i.test(normalized) ||
    normalized === "Москва" ||
    normalized === "Санкт-Петербург" ||
    normalized === "Севастополь"
  );
};
const PINNED_REGIONS = [
  "Москва",
  "Московская область",
  "Санкт-Петербург",
  "Ленинградская область",
  "Краснодарский край",
  "Республика Татарстан",
  "Свердловская область",
  "Челябинская область",
  "Самарская область",
  "Нижегородская область",
  "Тюменская область",
  "Новосибирская область"
];
const FOOTER_CONTACTS = {
  email: "fronteno@yandex.ru",
  telegram: "https://t.me/fronteno"
};

const pluralize = (value: number, one: string, few: string, many: string) => {
  const mod10 = value % 10;
  const mod100 = value % 100;

  if (mod10 === 1 && mod100 !== 11) {
    return one;
  }
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) {
    return few;
  }
  return many;
};

const loadSavedFilters = (): FiltersState => {
  if (typeof window === "undefined") {
    return initialFilters;
  }

  try {
    const rawValue = window.localStorage.getItem(FILTERS_STORAGE_KEY);
    if (!rawValue) {
      return initialFilters;
    }

    const parsed = JSON.parse(rawValue) as Partial<FiltersState>;
    const legacyCity = (parsed as { city?: string }).city;
    const legacyCategory = (parsed as { category?: string }).category;

    return {
      ...initialFilters,
      ...parsed,
      q: typeof parsed.q === "string" ? parsed.q : "",
      dateFrom: typeof parsed.dateFrom === "string" ? parsed.dateFrom : "",
      dateTo: typeof parsed.dateTo === "string" ? parsed.dateTo : "",
      sortBy: parsed.sortBy === "date_desc" ? "date_desc" : "date_asc",
      includePast: Boolean(parsed.includePast),
      cities: Array.isArray(parsed.cities) ? parsed.cities : legacyCity ? [legacyCity] : [],
      categories: Array.isArray(parsed.categories)
        ? parsed.categories.map((category) => normalizeCategoryLabel(category) ?? category)
        : legacyCategory
          ? [normalizeCategoryLabel(legacyCategory) ?? legacyCategory]
          : []
    };
  } catch {
    return initialFilters;
  }
};

function App() {
  const [filters, setFilters] = useState<FiltersState>(loadSavedFilters);
  const [page, setPage] = useState(1);
  const [filtersCloseSignal, setFiltersCloseSignal] = useState(0);
  const { data, loading, error } = useEvents(filters, page);
  const availableRegions = data.available_cities
    .filter(isPureRegionOption)
    .sort((left, right) => left.localeCompare(right, "ru"));
  const popularRegions = [
    ...PINNED_REGIONS.filter((region) => availableRegions.includes(region)),
    ...availableRegions.filter((region) => !PINNED_REGIONS.includes(region))
  ].slice(0, 12);
  const resultsSummary = `${data.total} ${pluralize(data.total, "событие", "события", "событий")} • ${data.total_regions} ${pluralize(data.total_regions, "регион", "региона", "регионов")} • ${data.total_categories} ${pluralize(data.total_categories, "вид спорта", "вида спорта", "видов спорта")}`;

  useEffect(() => {
    window.localStorage.setItem(FILTERS_STORAGE_KEY, JSON.stringify(filters));
  }, [filters]);

  useEffect(() => {
    setPage(1);
  }, [filters]);

  const navigateToPage = (nextPage: number) => {
    setPage(nextPage);
    setFiltersCloseSignal((current) => current + 1);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  return (
    <div className="page-shell">
      <header className="hero">
        <div className="hero__brand">
          <img className="hero__logo" src="/logo-mark.svg" alt="" aria-hidden="true" />
          <h1>sporly</h1>
        </div>
        <p className="hero__brand-text">поиск спортивных событий</p>
      </header>
      <FiltersPanel
        filters={filters}
        cities={availableRegions}
        popularCities={popularRegions}
        totalEvents={data.total}
        closeSignal={filtersCloseSignal}
        onChange={(next) => setFilters(next)}
        onReset={() => {
          setFilters(initialFilters);
          setPage(1);
        }}
      />

      {!loading && !error ? (
        <div className="results-summary" aria-live="polite">
          {resultsSummary}
        </div>
      ) : null}

      {error ? (
        <section className="empty-state empty-state--error">
          <h2>Серверы и админы укатили в закат</h2>
          <p>Попробуйте зайти чуть позже или покатайтесь.</p>
        </section>
      ) : null}
      {loading ? (
        <section className="loading-state" aria-live="polite" aria-busy="true">
          <div className="loading-state__mark">
            <img src="/logo-mark.svg" alt="" aria-hidden="true" />
          </div>
          <div className="loading-state__copy">
            <h2>Ищем спортивные события</h2>
            <p>Подгружаю свежие старты из всех источников</p>
          </div>
          <div className="loading-state__tracks" aria-hidden="true">
            <span className="loading-state__track loading-state__track--wide" />
            <span className="loading-state__track loading-state__track--mid" />
            <span className="loading-state__track loading-state__track--narrow" />
          </div>
        </section>
      ) : null}

      {!loading && !error && data.items.length === 0 ? (
        <section className="empty-state">
          <h2>Пока ничего не нашлось</h2>
          <p>
            Попробуйте изменить даты, убрать часть ограничений или выбрать другой
            регион и вид спорта.
          </p>
        </section>
      ) : null}

      <section className="events-grid">
        {data.items.map((event) => (
          <EventCard key={event.id} event={event} />
        ))}
      </section>

      {!loading && !error && data.total_pages > 1 ? (
        <nav className="pagination" aria-label="Пагинация событий">
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

      <section className="seo-copy" aria-labelledby="seo-copy-title">
        <h2 id="seo-copy-title">Спортивные события в одном каталоге</h2>
        <p>
          Sporly помогает находить забеги, велогонки, лыжные марафоны, триатлон,
          ориентирование и другие старты по России и ближнему зарубежью в одном месте.
        </p>
        <p>
          Здесь можно быстро выбрать регион, даты и вид спорта, чтобы найти подходящие
          соревнования, фестивали и старты из разных источников в едином формате.
        </p>
      </section>

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
}

export default App;
