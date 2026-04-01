import { normalizeCategoryLabel, slugifyCategory } from "../categories";
import { EventItem } from "../types/events";

type EventCardProps = {
  event: EventItem;
};

const formatDate = (value: string | null, fallback: string | null) => {
  if (!value) return fallback ?? "Дата не указана";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return fallback ?? value;
  const hasExplicitTime =
    parsed.getHours() !== 0 || parsed.getMinutes() !== 0 || parsed.getSeconds() !== 0;

  return new Intl.DateTimeFormat("ru-RU", {
    dateStyle: "medium",
    ...(hasExplicitTime ? { timeStyle: "short" as const } : {})
  }).format(parsed);
};

export const EventCard = ({ event }: EventCardProps) => {
  const location = event.city ?? "Город не указан";
  const categoryLabel = normalizeCategoryLabel(event.category) ?? event.category ?? "Спорт";
  const cardClass = `event-card--${slugifyCategory(categoryLabel)}`;
  const categoryClass = `event-card__category--${slugifyCategory(categoryLabel)}`;

  return (
    <article className={`event-card ${cardClass}`}>
      <a className="event-card__anchor" href={event.source_url} target="_blank" rel="noreferrer">
        <div className="event-card__content">
          <div className="event-card__meta">
            <span className={`event-card__category ${categoryClass}`}>
              {categoryLabel}
            </span>
          </div>

          <p className="event-card__date">{formatDate(event.starts_at, event.date_text)}</p>
          <h3>{event.title}</h3>
          <p className="event-card__location">{location}</p>

          {event.description ? <p className="event-card__description">{event.description}</p> : null}
        </div>
      </a>
    </article>
  );
};
