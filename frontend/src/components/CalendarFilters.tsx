import { MouseEvent, useEffect, useState } from "react";
import { slugifyCategory, SPORT_OPTIONS } from "../categories";
import { CalendarFiltersState } from "../types/events";

type CalendarFiltersProps = {
  filters: CalendarFiltersState;
  regions: string[];
  popularRegions: string[];
  onChange: (next: CalendarFiltersState) => void;
  onReset: () => void;
};

export const CalendarFilters = ({
  filters,
  regions,
  popularRegions,
  onChange,
  onReset
}: CalendarFiltersProps) => {
  const [isOpen, setIsOpen] = useState(false);
  const hasActiveFilters = filters.cities.length > 0 || filters.categories.length > 0;
  const summaryText = hasActiveFilters
    ? [...filters.categories, ...filters.cities].join(" • ")
    : "все виды спорта и регионы";

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

  const toggleCategory = (category: string) => {
    const next = filters.categories.includes(category)
      ? filters.categories.filter((item) => item !== category)
      : [...filters.categories, category];
    onChange({ ...filters, categories: next });
  };

  const toggleRegion = (region: string) => {
    const next = filters.cities.includes(region)
      ? filters.cities.filter((item) => item !== region)
      : [...filters.cities, region];
    onChange({ ...filters, cities: next });
  };

  const handleSummaryAction =
    (callback: () => void) =>
    (event: MouseEvent<HTMLButtonElement>) => {
      event.preventDefault();
      event.stopPropagation();
      callback();
    };

  return (
    <details
      className="filters calendar-filters"
      open={isOpen}
      onToggle={(event) => setIsOpen(event.currentTarget.open)}
    >
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
          {hasActiveFilters ? (
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
        <div className="filters__cluster">
          <span className="filters__subhead">Вид спорта</span>
          <div className="category-chips">
            {SPORT_OPTIONS.map((option) => (
              <button
                key={option}
                type="button"
                className={`category-chip category-chip--${slugifyCategory(option)}${
                  filters.categories.includes(option) ? " category-chip--active" : ""
                }`}
                onClick={() => toggleCategory(option)}
              >
                {option}
              </button>
            ))}
          </div>
        </div>

        <div className="filters__cluster">
          <div className="calendar-filters__region-head">
            <span className="filters__subhead">Область</span>
            <select
              className="calendar-filters__region-select"
              value=""
              onChange={(event) => {
                const region = event.target.value;
                if (region && !filters.cities.includes(region)) {
                  toggleRegion(region);
                }
              }}
            >
              <option value="">Выберите область</option>
              {regions.map((region) => (
                <option key={region} value={region}>
                  {region}
                </option>
              ))}
            </select>
          </div>
          <div className="city-chips">
            {popularRegions.map((region) => (
              <button
                key={region}
                type="button"
                className={`city-chip${filters.cities.includes(region) ? " city-chip--active" : ""}`}
                onClick={() => toggleRegion(region)}
              >
                {region}
              </button>
            ))}
          </div>
        </div>

        {hasActiveFilters ? (
          <div className="filters__cluster filters__cluster--selected">
            <span className="filters__subhead">Выбрано</span>
            <div className="selected-chips">
              {filters.categories.map((category) => (
                <button
                  key={category}
                  type="button"
                  className={`selected-chip category-chip--${slugifyCategory(category)}`}
                  onClick={() => toggleCategory(category)}
                >
                  {category} ×
                </button>
              ))}
              {filters.cities.map((region) => (
                <button
                  key={region}
                  type="button"
                  className="selected-chip"
                  onClick={() => toggleRegion(region)}
                >
                  {region} ×
                </button>
              ))}
            </div>
          </div>
        ) : null}
      </div>
    </details>
  );
};
