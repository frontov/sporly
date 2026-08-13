import { ReactNode } from "react";
import { slugifyCategory } from "../categories";
import { buildMonthGrid, groupEventsByDay, MONTH_LABELS, startOfMonth, toDayKey, WEEKDAY_LABELS } from "../calendarUtils";
import { CalendarEventItem } from "../types/events";

type CalendarViewProps = {
  month: Date;
  events: CalendarEventItem[];
  selectedDay: string | null;
  onMonthChange: (nextMonth: Date) => void;
  onSelectDay: (day: string | null) => void;
  viewToggle?: ReactNode;
};

export const CalendarView = ({
  month,
  events,
  selectedDay,
  onMonthChange,
  onSelectDay,
  viewToggle
}: CalendarViewProps) => {
  const eventsByDay = groupEventsByDay(events);
  const days = buildMonthGrid(month);
  const todayKey = toDayKey(new Date());
  const currentMonthIndex = month.getMonth();

  return (
    <div className="calendar-view">
      <div className="calendar-view__toolbar">
        <button
          type="button"
          className="calendar-view__nav-button"
          onClick={() => onMonthChange(new Date(month.getFullYear(), month.getMonth() - 1, 1))}
          aria-label="Предыдущий месяц"
        >
          ←
        </button>
        <span className="calendar-view__title">
          {MONTH_LABELS[currentMonthIndex]} {month.getFullYear()}
        </span>
        <button
          type="button"
          className="calendar-view__nav-button"
          onClick={() => onMonthChange(new Date(month.getFullYear(), month.getMonth() + 1, 1))}
          aria-label="Следующий месяц"
        >
          →
        </button>
        <button
          type="button"
          className="calendar-view__today-button"
          onClick={() => onMonthChange(startOfMonth(new Date()))}
        >
          Сегодня
        </button>
        {viewToggle}
      </div>

      <div className="calendar-view__weekdays">
        {WEEKDAY_LABELS.map((label) => (
          <span key={label} className="calendar-view__weekday">
            {label}
          </span>
        ))}
      </div>

      <div className="calendar-view__grid">
        {days.map((day) => {
          const key = toDayKey(day);
          const dayEvents = eventsByDay.get(key) ?? [];
          const isOtherMonth = day.getMonth() !== currentMonthIndex;
          const isToday = key === todayKey;
          const isSelected = key === selectedDay;
          const categories = Array.from(
            new Set(dayEvents.map((event) => event.category ?? "Другие"))
          );
          const visibleCategories = categories.slice(0, 4);
          const extraCategoryCount = categories.length - visibleCategories.length;

          return (
            <button
              key={key}
              type="button"
              className={[
                "calendar-day",
                isOtherMonth ? "calendar-day--muted" : "",
                isToday ? "calendar-day--today" : "",
                isSelected ? "calendar-day--selected" : "",
                dayEvents.length ? "calendar-day--has-events" : ""
              ]
                .filter(Boolean)
                .join(" ")}
              onClick={() => onSelectDay(isSelected ? null : key)}
              disabled={dayEvents.length === 0}
            >
              <span className="calendar-day__number">{day.getDate()}</span>
              {dayEvents.length > 0 ? (
                <>
                  <span className="calendar-day__dots" aria-hidden="true">
                    {visibleCategories.map((category) => (
                      <span
                        key={category}
                        className={`calendar-day__dot category-chip--${slugifyCategory(category)}`}
                      />
                    ))}
                    {extraCategoryCount > 0 ? (
                      <span className="calendar-day__dot-more">+{extraCategoryCount}</span>
                    ) : null}
                  </span>
                  <span className="calendar-day__count">{dayEvents.length}</span>
                </>
              ) : null}
            </button>
          );
        })}
      </div>
    </div>
  );
};
