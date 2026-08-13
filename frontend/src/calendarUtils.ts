import { CalendarEventItem } from "./types/events";

export const toDayKey = (date: Date) => {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
};

export const startOfMonth = (month: Date) => new Date(month.getFullYear(), month.getMonth(), 1);

export const groupEventsByDay = (events: CalendarEventItem[]) => {
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
  return eventsByDay;
};

export const MONTH_LABELS = [
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

export const MONTH_LABELS_SHORT = [
  "Янв",
  "Фев",
  "Март",
  "Апр",
  "Май",
  "Июнь",
  "Июль",
  "Авг",
  "Сен",
  "Окт",
  "Ноя",
  "Дек"
];

export const WEEKDAY_LABELS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];
export const WEEKDAY_LABELS_SHORT = ["П", "В", "С", "Ч", "П", "С", "В"];

export const buildMonthGrid = (month: Date) => {
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
