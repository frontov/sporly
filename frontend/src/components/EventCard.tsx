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
  const isMvmSeries =
    event.description?.includes("Серия МВМ 2026") ||
    event.title.includes("МВМ") ||
    event.source_url.includes("velomarathon");
  const isTriNitiSeries = event.description?.includes("TRI NITI CUP 2026") ?? false;
  const description =
    event.description?.trim() === "Серия МВМ 2026" ? null : event.description;
  const cardClass = `event-card--${slugifyCategory(categoryLabel)}`;
  const categoryClass = `event-card__category--${slugifyCategory(categoryLabel)}`;

  return (
    <article
      className={`event-card ${cardClass} ${isMvmSeries ? "event-card--mvm" : ""} ${isTriNitiSeries ? "event-card--tri-niti" : ""}`}
    >
      <a className="event-card__anchor" href={event.source_url} target="_blank" rel="noreferrer">
        <div className="event-card__content">
          <div className="event-card__meta">
            <span className={`event-card__category ${categoryClass}`}>
              {categoryLabel}
            </span>
            {isMvmSeries ? (
              <span className="event-card__series event-card__series--mvm" aria-label="Серия МВМ">
                <img
                  className="event-card__series-icon"
                  src="https://static.tildacdn.com/tild3163-3765-4636-b866-346666336666/ava_mvm_main.png"
                  alt=""
                  loading="lazy"
                />
                <span>МВМ</span>
              </span>
            ) : null}
            {isTriNitiSeries ? (
              <span className="event-card__series event-card__series--tri-niti" aria-label="TRI NITI CUP">
                <img
                  className="event-card__series-icon"
                  src="https://cup.marzocchi.ru/project/img/footer-logo.png"
                  alt=""
                  loading="lazy"
                />
                <span>TRI NITI</span>
              </span>
            ) : null}
          </div>

          <p className="event-card__date">{formatDate(event.starts_at, event.date_text)}</p>
          <h3>{event.title}</h3>
          <p className="event-card__location">{location}</p>

          {description ? <p className="event-card__description">{description}</p> : null}
        </div>
      </a>
    </article>
  );
};
