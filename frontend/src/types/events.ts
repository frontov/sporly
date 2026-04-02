export type EventItem = {
  id: string;
  title: string;
  description: string | null;
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

export type FiltersState = {
  q: string;
  cities: string[];
  categories: string[];
  dateFrom: string;
  dateTo: string;
  sortBy: "date_asc" | "date_desc";
  includePast: boolean;
};
