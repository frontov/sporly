export type EventItem = {
  id: string;
  title: string;
  description: string | null;
  series_slug: string | null;
  series_name: string | null;
  source_label: string | null;
  source_type: string | null;
  registration_status: string | null;
  last_checked_at: string | null;
  distance_summary: string | null;
  participation_format: string | null;
  kids_available: boolean | null;
  organizer_name: string | null;
  price_from: string | null;
  registration_deadline: string | null;
  slots_status: string | null;
  surface_type: string | null;
  difficulty_level: string | null;
  city: string | null;
  venue: string | null;
  category: string | null;
  date_text: string | null;
  starts_at: string | null;
  source_name: string;
  source_url: string;
  image_url: string | null;
};

export type EventsResponse = {
  items: EventItem[];
  is_loading: boolean;
  total: number;
  total_regions: number;
  total_categories: number;
  page: number;
  page_size: number;
  total_pages: number;
  available_cities: string[];
  available_categories: string[];
  available_sources: string[];
};

export type CalendarEventItem = {
  id: string;
  title: string;
  city: string | null;
  region: string | null;
  category: string | null;
  date_text: string | null;
  starts_at: string | null;
  source_name: string;
  source_url: string;
};

export type CalendarEventsResponse = {
  items: CalendarEventItem[];
  is_loading: boolean;
  total: number;
  available_cities: string[];
  available_categories: string[];
};

export type CalendarFiltersState = {
  cities: string[];
  categories: string[];
};

export type FiltersState = {
  q: string;
  cities: string[];
  categories: string[];
  recommended: boolean;
  showDetails: boolean;
  registrationStatus: string;
  kidsOnly: boolean;
  surfaceType: string;
  difficultyLevel: string;
  dateFrom: string;
  dateTo: string;
  sortBy: "date_asc" | "date_desc";
  includePast: boolean;
};
