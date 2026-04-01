export const slugifyCategory = (value: string | null) =>
  (value ?? "unknown")
    .toLowerCase()
    .replace(/[^a-zа-я0-9]+/gi, "-")
    .replace(/^-+|-+$/g, "");

const CATEGORY_ALIASES: Record<string, string> = {
  "ARDF, радиоспорт": "ARDF, радиоспорт",
  ARDF: "ARDF, радиоспорт",
  радиоспорт: "ARDF, радиоспорт",
  Бадминтон: "Бадминтон",
  Бег: "Бег",
  Велоспорт: "Велоспорт",
  "Водный спорт": "Плавание",
  Плавание: "Плавание",
  ГТО: "ГТО",
  "Детские старты": "Детские старты",
  Другие: "Другие",
  Единоборства: "Единоборства",
  Лыжи: "Лыжи",
  Триатлон: "Триатлон",
  Ходьба: "Ходьба",
  "Ориентирование и туризм": "Ориентирование и туризм",
  "Легкая атлетика": "Другие"
};

export const normalizeCategoryLabel = (value: string | null) => {
  if (!value) {
    return null;
  }
  return CATEGORY_ALIASES[value] ?? value;
};

export const SPORT_OPTIONS = [
  "ARDF, радиоспорт",
  "Бадминтон",
  "Бег",
  "Велоспорт",
  "Плавание",
  "ГТО",
  "Детские старты",
  "Другие",
  "Единоборства",
  "Лыжи",
  "Ориентирование и туризм",
  "Триатлон",
  "Ходьба"
];
