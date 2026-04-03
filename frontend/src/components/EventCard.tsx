import { normalizeCategoryLabel, slugifyCategory } from "../categories";
import { EventItem } from "../types/events";

type EventCardProps = {
  event: EventItem;
};

const SERIES_META: Record<
  string,
  {
    label: string;
    className: string;
    icon: string;
    ariaLabel: string;
  }
> = {
  mvm: {
    label: "МВМ",
    className: "event-card__series--mvm",
    icon: "https://static.tildacdn.com/tild3163-3765-4636-b866-346666336666/ava_mvm_main.png",
    ariaLabel: "Серия МВМ"
  },
  tri_niti: {
    label: "TRI NITI",
    className: "event-card__series--tri-niti",
    icon: "https://cup.marzocchi.ru/project/img/footer-logo.png",
    ariaLabel: "TRI NITI CUP"
  },
  open_band: {
    label: "OPEN BAND",
    className: "event-card__series--open-band",
    icon: "https://static.tildacdn.com/tild3361-6131-4266-b961-363731663532/OB__.svg",
    ariaLabel: "OPEN BAND"
  },
  russialoppet: {
    label: "RUSSIALOPPET",
    className: "event-card__series--russialoppet",
    icon: "https://russialoppet.ru/upload/aspro.mshop/7bb/7bbb7a3ee7846d26f07d22eefd3769ca.png",
    ariaLabel: "RUSSIALOPPET"
  },
  running_community: {
    label: "RUNC",
    className: "event-card__series--running-community",
    icon: "https://runc.run/static/main/img/header-logo-ru.svg",
    ariaLabel: "Running Community"
  }
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
  const series = event.series_slug ? SERIES_META[event.series_slug] : null;
  const description =
    event.series_slug === "mvm" && event.description?.trim() === "Серия МВМ 2026"
      ? null
      : event.description;
  const cardClass = `event-card--${slugifyCategory(categoryLabel)}`;
  const categoryClass = `event-card__category--${slugifyCategory(categoryLabel)}`;
  const seriesCardClass = event.series_slug ? `event-card--${event.series_slug.replace(/_/g, "-")}` : "";

  return (
    <article
      className={`event-card ${cardClass} ${seriesCardClass}`}
    >
      <a className="event-card__anchor" href={event.source_url} target="_blank" rel="noreferrer">
        <div className="event-card__content">
          <div className="event-card__meta">
            <span className={`event-card__category ${categoryClass}`}>
              {categoryLabel}
            </span>
            {series ? (
              <span className={`event-card__series ${series.className}`} aria-label={series.ariaLabel}>
                <img
                  className="event-card__series-icon"
                  src={series.icon}
                  alt=""
                  loading="lazy"
                />
                <span>{series.label}</span>
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
