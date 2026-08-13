export const isPureRegionOption = (value: string) => {
  const normalized = value.trim();
  if (!normalized || normalized.includes(",") || normalized.includes(" и ")) {
    return false;
  }

  return (
    /(область|край|республика|автономный округ)$/i.test(normalized) ||
    normalized === "Москва" ||
    normalized === "Санкт-Петербург" ||
    normalized === "Севастополь"
  );
};

export const PINNED_REGIONS = [
  "Москва",
  "Московская область",
  "Санкт-Петербург",
  "Ленинградская область",
  "Краснодарский край",
  "Республика Татарстан",
  "Свердловская область",
  "Челябинская область",
  "Самарская область",
  "Нижегородская область",
  "Тюменская область",
  "Новосибирская область"
];

export const sortRegions = (regions: string[]) =>
  [...regions].sort((left, right) => left.localeCompare(right, "ru"));

export const popularRegionsOf = (availableRegions: string[], limit = 12) =>
  [
    ...PINNED_REGIONS.filter((region) => availableRegions.includes(region)),
    ...availableRegions.filter((region) => !PINNED_REGIONS.includes(region))
  ].slice(0, limit);
