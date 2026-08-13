import { useEffect, useMemo, useState } from "react";
import { startOfMonth } from "./calendarUtils";
import { slugifyCategory } from "./categories";
import { CalendarFilters } from "./components/CalendarFilters";
import { CalendarView } from "./components/CalendarView";
import { CalendarYearView } from "./components/CalendarYearView";
import { useCalendarEvents } from "./hooks/useCalendarEvents";
import { useIsDesktop } from "./hooks/useIsDesktop";
import { navigateLinkProps, useRoute } from "./hooks/useRoute";
import { isPureRegionOption, popularRegionsOf, sortRegions } from "./regions";
import { CalendarFiltersState } from "./types/events";

type ViewMode = "month" | "year";

const CALENDAR_FILTERS_STORAGE_KEY = "sporly.calendarFilters";

const initialFilters: CalendarFiltersState = {
  cities: [],
  categories: []
};

const loadSavedFilters = (): CalendarFiltersState => {
  if (typeof window === "undefined") {
    return initialFilters;
  }
  try {
    const raw = window.localStorage.getItem(CALENDAR_FILTERS_STORAGE_KEY);
    if (!raw) {
      return initialFilters;
    }
    const parsed = JSON.parse(raw) as Partial<CalendarFiltersState>;
    return {
      cities: Array.isArray(parsed.cities) ? parsed.cities : [],
      categories: Array.isArray(parsed.categories) ? parsed.categories : []
    };
  } catch {
    return initialFilters;
  }
};

export const CalendarPage = () => {
  const { navigate } = useRoute();
  const isDesktop = useIsDesktop();
  const [filters, setFilters] = useState<CalendarFiltersState>(loadSavedFilters);
  const [month, setMonth] = useState<Date>(() => startOfMonth(new Date()));
  const [viewMode, setViewMode] = useState<ViewMode>("month");
  const [selectedDay, setSelectedDay] = useState<string | null>(null);
  const { data, loading, error } = useCalendarEvents(filters);
  const effectiveViewMode: ViewMode = isDesktop ? viewMode : "month";

  const viewToggle = isDesktop ? (
    <div className="calendar-view-toggle" role="group" aria-label="Режим отображения">
      <button
        type="button"
        className={`calendar-view-toggle__option${effectiveViewMode === "month" ? " calendar-view-toggle__option--active" : ""}`}
        onClick={() => setViewMode("month")}
      >
        Месяц
      </button>
      <button
        type="button"
        className={`calendar-view-toggle__option${effectiveViewMode === "year" ? " calendar-view-toggle__option--active" : ""}`}
        onClick={() => setViewMode("year")}
      >
        Год
      </button>
    </div>
  ) : null;

  useEffect(() => {
    window.localStorage.setItem(CALENDAR_FILTERS_STORAGE_KEY, JSON.stringify(filters));
  }, [filters]);

  useEffect(() => {
    setSelectedDay(null);
  }, [filters, month]);

  const availableRegions = sortRegions(data.available_cities.filter(isPureRegionOption));
  const popularRegions = popularRegionsOf(availableRegions);

  const selectedDayEvents = useMemo(() => {
    if (!selectedDay) {
      return [];
    }
    return data.items
      .filter((event) => event.starts_at?.slice(0, 10) === selectedDay)
      .sort((left, right) => left.title.localeCompare(right.title, "ru"));
  }, [data.items, selectedDay]);

  const selectedDayLabel = selectedDay
    ? new Date(`${selectedDay}T00:00:00`).toLocaleDateString("ru-RU", {
        day: "numeric",
        month: "long",
        year: "numeric"
      })
    : null;

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
          </nav>
        </div>
        <p className="hero__brand-text">календарь спортивных событий</p>
      </header>

      <div className="calendar-page">
        <CalendarFilters
          filters={filters}
          regions={availableRegions}
          popularRegions={popularRegions}
          onChange={setFilters}
          onReset={() => setFilters(initialFilters)}
        />

        <div className="calendar-page__content">
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
                <h2>Собираем календарь</h2>
                <p>Раскладываем старты по датам</p>
              </div>
            </section>
          ) : null}

          {!loading && !error ? (
            <>
              {effectiveViewMode === "year" ? (
                <CalendarYearView
                  year={month.getFullYear()}
                  events={data.items}
                  selectedDay={selectedDay}
                  onYearChange={(nextYear) => setMonth(new Date(nextYear, month.getMonth(), 1))}
                  onSelectDay={setSelectedDay}
                  viewToggle={viewToggle}
                />
              ) : (
                <CalendarView
                  month={month}
                  events={data.items}
                  selectedDay={selectedDay}
                  onMonthChange={setMonth}
                  onSelectDay={setSelectedDay}
                  viewToggle={viewToggle}
                />
              )}

              {selectedDay ? (
                <section className="calendar-day-panel">
                  <div className="calendar-day-panel__head">
                    <h2>{selectedDayLabel}</h2>
                    <button
                      type="button"
                      className="calendar-day-panel__close"
                      onClick={() => setSelectedDay(null)}
                      aria-label="Закрыть"
                    >
                      ×
                    </button>
                  </div>
                  <ul className="calendar-day-panel__list">
                    {selectedDayEvents.map((event) => (
                      <li key={event.id} className="calendar-day-panel__item">
                        <a
                          href={event.source_url}
                          target="_blank"
                          rel="noreferrer"
                          className={`calendar-day-panel__link category-chip--${slugifyCategory(event.category)}`}
                        >
                          {event.title}
                        </a>
                        <span className="calendar-day-panel__meta">
                          {[event.category, event.city].filter(Boolean).join(" • ")}
                        </span>
                      </li>
                    ))}
                  </ul>
                </section>
              ) : null}
            </>
          ) : null}
        </div>
      </div>

      <footer className="site-footer">
        <span className="site-footer__brand">sporly</span>
        <span className="site-footer__item">помогаем искать спортивные события с 2026 года</span>
      </footer>
    </div>
  );
};
