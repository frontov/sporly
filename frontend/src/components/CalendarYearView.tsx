import { ReactNode } from "react";
import { buildMonthGrid, groupEventsByDay, MONTH_LABELS_SHORT, toDayKey, WEEKDAY_LABELS_SHORT } from "../calendarUtils";
import { CalendarEventItem } from "../types/events";

type CalendarYearViewProps = {
  year: number;
  events: CalendarEventItem[];
  selectedDay: string | null;
  onYearChange: (nextYear: number) => void;
  onSelectDay: (day: string | null) => void;
  viewToggle?: ReactNode;
};

const intensityClass = (count: number, maxCount: number) => {
  if (count === 0) {
    return "";
  }
  const ratio = count / Math.max(maxCount, 1);
  if (ratio > 0.66) {
    return "calendar-mini-day--heat-3";
  }
  if (ratio > 0.33) {
    return "calendar-mini-day--heat-2";
  }
  return "calendar-mini-day--heat-1";
};

export const CalendarYearView = ({
  year,
  events,
  selectedDay,
  onYearChange,
  onSelectDay,
  viewToggle
}: CalendarYearViewProps) => {
  const eventsByDay = groupEventsByDay(events);
  const todayKey = toDayKey(new Date());
  const maxCount = Math.max(1, ...Array.from(eventsByDay.values()).map((list) => list.length));

  return (
    <div className="calendar-view calendar-year-view">
      <div className="calendar-view__toolbar">
        <button
          type="button"
          className="calendar-view__nav-button"
          onClick={() => onYearChange(year - 1)}
          aria-label="Предыдущий год"
        >
          ←
        </button>
        <span className="calendar-view__title">{year}</span>
        <button
          type="button"
          className="calendar-view__nav-button"
          onClick={() => onYearChange(year + 1)}
          aria-label="Следующий год"
        >
          →
        </button>
        <button
          type="button"
          className="calendar-view__today-button"
          onClick={() => onYearChange(new Date().getFullYear())}
        >
          Сегодня
        </button>
        {viewToggle}
      </div>

      <div className="calendar-year-view__grid">
        {MONTH_LABELS_SHORT.map((label, monthIndex) => {
          const monthDate = new Date(year, monthIndex, 1);
          const days = buildMonthGrid(monthDate);

          return (
            <div key={label} className="calendar-mini-month">
              <span className="calendar-mini-month__title">{label}</span>
              <div className="calendar-mini-month__weekdays">
                {WEEKDAY_LABELS_SHORT.map((weekday, index) => (
                  <span key={`${label}-${weekday}-${index}`}>{weekday}</span>
                ))}
              </div>
              <div className="calendar-mini-month__grid">
                {days.map((day) => {
                  const key = toDayKey(day);
                  const dayEvents = eventsByDay.get(key) ?? [];
                  const isOtherMonth = day.getMonth() !== monthIndex;
                  const isToday = key === todayKey;
                  const isSelected = key === selectedDay;

                  return (
                    <button
                      key={key}
                      type="button"
                      className={[
                        "calendar-mini-day",
                        isOtherMonth ? "calendar-mini-day--muted" : "",
                        isToday ? "calendar-mini-day--today" : "",
                        isSelected ? "calendar-mini-day--selected" : "",
                        intensityClass(dayEvents.length, maxCount)
                      ]
                        .filter(Boolean)
                        .join(" ")}
                      disabled={dayEvents.length === 0}
                      onClick={() => onSelectDay(isSelected ? null : key)}
                      title={dayEvents.length ? `${dayEvents.length} событий` : undefined}
                    >
                      {day.getDate()}
                    </button>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
