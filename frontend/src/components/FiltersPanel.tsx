import { ChangeEvent, MouseEvent, useEffect, useState } from "react";
import { normalizeCategoryLabel, slugifyCategory, SPORT_OPTIONS } from "../categories";
import { FiltersState } from "../types/events";

type FiltersPanelProps = {
  filters: FiltersState;
  cities: string[];
  popularCities: string[];
  totalEvents: number;
  onChange: (next: FiltersState) => void;
  onReset: () => void;
};

export const FiltersPanel = ({
  filters,
  cities,
  popularCities,
  totalEvents,
  onChange,
  onReset
}: FiltersPanelProps) => {
  const [regionDraft, setRegionDraft] = useState("");
  const [isAdvancedOpen, setIsAdvancedOpen] = useState(false);
  const normalizedCategories = filters.categories.map(
    (category) => normalizeCategoryLabel(category) ?? category
  );
  const activeFilterLabels = [
    normalizedCategories.length ? normalizedCategories.join(", ") : "",
    filters.cities.length ? filters.cities.join(", ") : "",
    filters.q ? `Поиск: ${filters.q}` : "",
    filters.dateFrom ? `От ${filters.dateFrom}` : "",
    filters.dateTo ? `До ${filters.dateTo}` : "",
    filters.includePast ? "С прошедшими" : ""
  ].filter(Boolean);
  const activeFiltersCount = activeFilterLabels.length;
  const summaryText =
    activeFiltersCount > 0 ? activeFilterLabels.join(" • ") : "ближайшие события";
  const [isOpen, setIsOpen] = useState(activeFiltersCount > 0);

  useEffect(() => {
    if (activeFiltersCount > 0) {
      setIsOpen(true);
    }
  }, [activeFiltersCount]);

  useEffect(() => {
    if (filters.cities.length > 0 || Boolean(filters.q) || filters.includePast) {
      setIsAdvancedOpen(true);
    }
  }, [filters.cities.length, filters.includePast, filters.q]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }

    const isMobile = window.matchMedia("(max-width: 640px)").matches;
    if (!isMobile || !isOpen) {
      document.body.style.overflow = "";
      return;
    }

    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = "";
    };
  }, [isOpen]);

  const updateField =
    (field: keyof FiltersState) =>
    (
      event: ChangeEvent<HTMLInputElement> | ChangeEvent<HTMLSelectElement>
    ) => {
      onChange({
        ...filters,
        [field]: event.target.value
      });
    };

  const toggleCategory = (category: string) => {
    const normalizedCategory = normalizeCategoryLabel(category) ?? category;
    const nextCategories = normalizedCategories.includes(normalizedCategory)
      ? normalizedCategories.filter((item) => item !== normalizedCategory)
      : [...normalizedCategories, normalizedCategory];
    onChange({
      ...filters,
      categories: nextCategories
    });
  };

  const toggleCategoryGroup = (groupValues: string[]) => {
    const normalizedGroupValues = groupValues.map(
      (value) => normalizeCategoryLabel(value) ?? value
    );
    const isActive = normalizedGroupValues.every((value) =>
      normalizedCategories.includes(value)
    );
    const nextCategories = isActive
      ? normalizedCategories.filter((item) => !normalizedGroupValues.includes(item))
      : Array.from(new Set([...normalizedCategories, ...normalizedGroupValues]));

    onChange({
      ...filters,
      categories: nextCategories
    });
  };

  const toggleCity = (city: string) => {
    const nextCities = filters.cities.includes(city)
      ? filters.cities.filter((item) => item !== city)
      : [...filters.cities, city];
    onChange({
      ...filters,
      cities: nextCities
    });
  };

  const handleSummaryAction =
    (callback: () => void) =>
    (event: MouseEvent<HTMLButtonElement>) => {
      event.preventDefault();
      event.stopPropagation();
      callback();
    };

  const eventLabel =
    totalEvents % 10 === 1 && totalEvents % 100 !== 11
      ? "событие"
      : totalEvents % 10 >= 2 &&
          totalEvents % 10 <= 4 &&
          (totalEvents % 100 < 12 || totalEvents % 100 > 14)
        ? "события"
        : "событий";

  return (
    <details className="filters" open={isOpen} onToggle={(event) => setIsOpen(event.currentTarget.open)}>
      <summary className="filters__summary">
        <div className="filters__summary-copy">
          <span className="filters__summary-label">Фильтры</span>
          <span className="filters__summary-text">{summaryText}</span>
        </div>
        <div className="filters__summary-actions">
          <button
            type="button"
            className="filters__summary-action"
            onClick={handleSummaryAction(() => setIsOpen((current) => !current))}
          >
            {isOpen ? "Скрыть" : "Изменить"}
          </button>
          {activeFiltersCount > 0 ? (
            <button
              type="button"
              className="filters__summary-action filters__summary-action--ghost"
              onClick={handleSummaryAction(onReset)}
            >
              Сбросить
            </button>
          ) : null}
        </div>
      </summary>

      <div className="filters__body">
        <div className="filters__section">
          <div className="filters__section-head">
            <span className="filters__section-label">Базовые фильтры</span>
          </div>

          <div className="filters__toolbar filters__toolbar--basic">
            <label className="field field--compact">
              <span>Дата от</span>
              <input type="date" value={filters.dateFrom} onChange={updateField("dateFrom")} />
            </label>

            <label className="field field--compact">
              <span>Дата до</span>
              <input type="date" value={filters.dateTo} onChange={updateField("dateTo")} />
            </label>
          </div>

          <div className="filters__cluster">
            <span className="filters__subhead">Вид спорта</span>
            <div className="category-chips">
              {SPORT_OPTIONS.map((option) => (
                <button
                  key={option}
                  type="button"
                  className={`category-chip category-chip--${slugifyCategory(option)}${
                    normalizedCategories.includes(option)
                      ? " category-chip--active"
                      : ""
                  }`}
                  onClick={() => toggleCategoryGroup([option])}
                >
                  {option}
                </button>
              ))}
            </div>
          </div>
        </div>

        <details
          className="filters__advanced-panel"
          open={isAdvancedOpen}
          onToggle={(event) => setIsAdvancedOpen(event.currentTarget.open)}
        >
          <summary className="filters__advanced-toggle">
            Расширенные фильтры
          </summary>

          <div className="filters__section filters__section--advanced">
            <div className="filters__toolbar filters__toolbar--advanced">
              <label className="field field--compact field--city">
                <span>Область</span>
                <select
                  value={regionDraft}
                  onChange={(event) => {
                    const nextRegion = event.target.value;
                    setRegionDraft(nextRegion);
                    if (!nextRegion) {
                      return;
                    }
                    if (!filters.cities.includes(nextRegion)) {
                      onChange({
                        ...filters,
                        cities: [...filters.cities, nextRegion]
                      });
                    }
                    setRegionDraft("");
                  }}
                >
                  <option value="">Выберите область</option>
                  {cities.map((city) => (
                    <option key={city} value={city}>
                      {city}
                    </option>
                  ))}
                </select>
              </label>

              <label className="field field--compact field--search">
                <span>Поиск по названию</span>
                <input
                  type="search"
                  placeholder="Бег, велозаезд, турнир..."
                  value={filters.q}
                  onChange={updateField("q")}
                />
              </label>

              <label className="field field--compact">
                <span>Сортировка</span>
                <select value={filters.sortBy} onChange={updateField("sortBy")}>
                  <option value="date_asc">Сначала ближайшие</option>
                  <option value="date_desc">Сначала поздние</option>
                </select>
              </label>
            </div>

            <div className="filters__cluster">
              <span className="filters__subhead">Популярные регионы</span>
              <div className="city-chips">
                {popularCities.map((city) => (
                  <button
                    key={city}
                    type="button"
                    className={`city-chip${filters.cities.includes(city) ? " city-chip--active" : ""}`}
                    onClick={() => toggleCity(city)}
                  >
                    {city}
                  </button>
                ))}
              </div>
            </div>

            {(filters.cities.length > 0 || normalizedCategories.length > 0) ? (
              <div className="filters__cluster filters__cluster--selected">
                <span className="filters__subhead">Выбрано</span>
                <div className="selected-chips">
                  {normalizedCategories.map((category) => (
                    <button
                      key={category}
                      type="button"
                      className={`selected-chip category-chip--${slugifyCategory(category)}`}
                      onClick={() => toggleCategory(category)}
                    >
                      {category} ×
                    </button>
                  ))}
                  {filters.cities.map((city) => (
                    <button
                      key={city}
                      type="button"
                      className="selected-chip"
                      onClick={() => toggleCity(city)}
                    >
                      {city} ×
                    </button>
                  ))}
                </div>
              </div>
            ) : null}
          </div>
        </details>

        <div className="filters__actions">
          <label className="toggle">
            <input
              type="checkbox"
              checked={filters.includePast}
              onChange={(event) =>
                onChange({
                  ...filters,
                  includePast: event.target.checked
                })
              }
            />
            <span>Показывать прошедшие</span>
          </label>

          <button type="button" className="filters__reset" onClick={onReset}>
            Сбросить фильтры
          </button>

          <button
            type="button"
            className="filters__apply"
            onClick={() => setIsOpen(false)}
          >
            Показать {totalEvents} {eventLabel}
          </button>
        </div>
        <p className="filters__hint">
          Если даты не выбраны, показываются только предстоящие мероприятия.
        </p>
      </div>
    </details>
  );
};
