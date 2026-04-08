import { useRef } from "react";
import { normalizeCategoryLabel, slugifyCategory } from "../categories";
import { EventItem } from "../types/events";

type EventCardProps = {
  event: EventItem;
  showDetails: boolean;
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

const REGISTRATION_STATUS_LABELS: Record<
  string,
  { text: string; className: string }
> = {
  open: { text: "Регистрация открыта", className: "event-card__trust-chip--open" },
  closed: { text: "Регистрация закрыта", className: "event-card__trust-chip--closed" },
  limited: { text: "Лист ожидания", className: "event-card__trust-chip--limited" }
};

const formatCheckedAt = (value: string | null) => {
  if (!value) return null;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return null;
  const diffHours = Math.max(0, Math.floor((Date.now() - parsed.getTime()) / 3_600_000));
  if (diffHours < 24) return "Проверено сегодня";
  if (diffHours < 48) return "Проверено вчера";
  const days = Math.floor(diffHours / 24);
  return `Проверено ${days} дн. назад`;
};

const buildDecisionFacts = (event: EventItem) => {
  const facts: string[] = [];
  if (event.distance_summary) facts.push(event.distance_summary);
  if (event.registration_deadline) facts.push(event.registration_deadline);
  if (event.surface_type) facts.push(event.surface_type);
  if (event.participation_format) facts.push(event.participation_format);
  return facts.slice(0, 3);
};

export const EventCard = ({ event, showDetails }: EventCardProps) => {
  const lastOpenAtRef = useRef(0);
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
  const registrationChip = event.registration_status
    ? REGISTRATION_STATUS_LABELS[event.registration_status]
    : null;
  const checkedAtLabel = formatCheckedAt(event.last_checked_at);
  const decisionFacts = buildDecisionFacts(event);
  const trustFacts = [
    event.source_label ? `Источник: ${event.source_label}` : "",
    checkedAtLabel ?? ""
  ].filter(Boolean);

  const openEvent = () => {
    const now = Date.now();
    if (now - lastOpenAtRef.current < 1000) {
      return;
    }
    lastOpenAtRef.current = now;
    window.open(event.source_url, "_blank", "noopener,noreferrer");
  };

  const handleClick = (clickEvent: React.MouseEvent<HTMLAnchorElement>) => {
    clickEvent.preventDefault();
    openEvent();
  };

  const handleKeyDown = (keyEvent: React.KeyboardEvent<HTMLAnchorElement>) => {
    if (keyEvent.key !== "Enter" && keyEvent.key !== " ") {
      return;
    }
    keyEvent.preventDefault();
    openEvent();
  };

  return (
    <article
      className={`event-card ${cardClass} ${seriesCardClass}`}
    >
      <a
        className="event-card__anchor"
        href={event.source_url}
        target="_blank"
        rel="noreferrer"
        onClick={handleClick}
        onKeyDown={handleKeyDown}
      >
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

        <div className="event-card__content">
          <div className="event-card__meta">
            <span className={`event-card__category ${categoryClass}`}>
              {categoryLabel}
            </span>
          </div>

          <p className="event-card__date">{formatDate(event.starts_at, event.date_text)}</p>
          <h3>{event.title}</h3>
          <p className="event-card__location">{location}</p>

          {description ? <p className="event-card__description">{description}</p> : null}

          {showDetails && decisionFacts.length ? (
            <div className="event-card__facts">
              {decisionFacts.map((fact) => (
                <span key={fact} className="event-card__fact">
                  {fact}
                </span>
              ))}
            </div>
          ) : null}

          {showDetails && registrationChip ? (
            <div className="event-card__trust">
              <span className={`event-card__trust-chip ${registrationChip.className}`}>
                {registrationChip.text}
              </span>
            </div>
          ) : null}

          {trustFacts.length ? (
            <div className="event-card__footer">
              <span className="event-card__trust-line">{trustFacts.join(" • ")}</span>
            </div>
          ) : null}
        </div>
      </a>
    </article>
  );
};
