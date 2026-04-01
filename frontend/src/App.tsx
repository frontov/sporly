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
const isRegionOption = (value: string) =>
  /(область|край|республика|автономный округ)$/i.test(value) ||
  value === "Москва" ||
  value === "Санкт-Петербург" ||
  value === "Севастополь";
const isLegacyCombinedRegion = (value: string) => value.includes(" и ");
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
  const { data, loading, error } = useEvents(filters, page);
  const availableRegions = data.available_cities
    .filter((value) => isRegionOption(value) && !isLegacyCombinedRegion(value));
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

  return (
    <div className="page-shell">
      <header className="hero">
        <h1>sporly</h1>
        <p className="hero__brand-text">поиск спортивных событий</p>
      </header>
      <FiltersPanel
        filters={filters}
        cities={availableRegions}
        popularCities={popularRegions}
        totalEvents={data.total}
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

      {error ? <div className="state-banner state-banner--error">{error}</div> : null}
      {loading ? <div className="state-banner">Загружаю каталог...</div> : null}

      {!loading && !error && data.items.length === 0 ? (
        <section className="empty-state">
          <h2>Такие мероприятия еще никто не решился провести</h2>
          <p>
            По текущим фильтрам событий не нашлось. Попробуйте расширить даты, убрать часть
            ограничений или выбрать другой город и вид спорта.
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
          <button type="button" onClick={() => setPage((current) => Math.max(current - 1, 1))} disabled={data.page <= 1}>
            Назад
          </button>
          <span>
            Страница {data.page} из {data.total_pages}
          </span>
          <button
            type="button"
            onClick={() => setPage((current) => Math.min(current + 1, data.total_pages))}
            disabled={data.page >= data.total_pages}
          >
            Вперёд
          </button>
        </nav>
      ) : null}

      <footer className="site-footer">
        <span className="site-footer__brand">sporly</span>
        <span className="site-footer__item">
          поиск спортивных событий по датам, городам и видам спорта в одном едином каталоге
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
