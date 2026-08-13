import { slugifyCategory } from "../categories";
import { CalendarEventItem } from "../types/events";

type CalendarViewProps = {
  month: Date;
  events: CalendarEventItem[];
  selectedDay: string | null;
  onMonthChange: (nextMonth: Date) => void;
  onSelectDay: (day: string | null) => void;
};

const WEEKDAY_LABELS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];
const MONTH_LABELS = [
  "Январь",
  "Февраль",
  "Март",
  "Апрель",
  "Май",
  "Июнь",
  "Июль",
  "Август",
  "Сентябрь",
  "Октябрь",
  "Ноябрь",
  "Декабрь"
];

const toDayKey = (date: Date) => {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
};

const startOfMonth = (month: Date) => new Date(month.getFullYear(), month.getMonth(), 1);

const buildMonthGrid = (month: Date) => {
  const first = startOfMonth(month);
  const firstWeekday = (first.getDay() + 6) % 7;
  const gridStart = new Date(first);
  gridStart.setDate(gridStart.getDate() - firstWeekday);

  const days: Date[] = [];
  for (let i = 0; i < 42; i += 1) {
    const day = new Date(gridStart);
    day.setDate(gridStart.getDate() + i);
    days.push(day);
  }
  return days;
};

export const CalendarView = ({
  month,
  events,
  selectedDay,
  onMonthChange,
  onSelectDay
}: CalendarViewProps) => {
  const eventsByDay = new Map<string, CalendarEventItem[]>();
  for (const event of events) {
    if (!event.starts_at) {
      continue;
    }
    const key = event.starts_at.slice(0, 10);
    const bucket = eventsByDay.get(key);
    if (bucket) {
      bucket.push(event);
    } else {
      eventsByDay.set(key, [event]);
    }
  }

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

export { toDayKey, startOfMonth };
