import { useEffect, useState } from "react";
import { EventsResponse, FiltersState } from "../types/events";

const buildQuery = (filters: FiltersState, page: number) => {
  const params = new URLSearchParams();
  const today = new Date().toISOString().slice(0, 10);
  const effectiveDateFrom =
    filters.dateFrom || (!filters.includePast && !filters.dateFrom && !filters.dateTo ? today : "");

  if (filters.q) params.set("q", filters.q);
  filters.cities.forEach((city) => params.append("city", city));
  filters.categories.forEach((category) => params.append("category", category));
  if (filters.recommended) params.set("recommended", "true");
  if (effectiveDateFrom) params.set("date_from", effectiveDateFrom);
  if (filters.dateTo) params.set("date_to", filters.dateTo);
  params.set("sort_by", filters.sortBy);
  params.set("page", String(page));
  params.set("page_size", "24");

  return params.toString();
};

export const useEvents = (filters: FiltersState, page: number) => {
  const [data, setData] = useState<EventsResponse>({
    items: [],
    is_loading: false,
    total: 0,
    total_regions: 0,
    total_categories: 0,
    page: 1,
    page_size: 24,
    total_pages: 1,
    available_cities: [],
    available_categories: [],
    available_sources: []
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    let retryTimer: number | undefined;

    const load = async (showLoading = true) => {
      retryTimer = undefined;
      if (showLoading) {
        setLoading(true);
      }
      setError(null);

      try {
        const query = buildQuery(filters, page);
        const response = await fetch(`/api/events${query ? `?${query}` : ""}`, {
          signal: controller.signal
        });

        if (!response.ok) {
          throw new Error(`Backend returned ${response.status}`);
        }

        const payload = (await response.json()) as EventsResponse;
        setData(payload);
        if (payload.is_loading) {
          retryTimer = window.setTimeout(() => {
            void load(false);
          }, 1500);
          return;
        }
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") {
          return;
        }
        setError("Не удалось загрузить события. Проверьте backend и конфиг источников.");
      } finally {
        if (!controller.signal.aborted && retryTimer === undefined) {
          setLoading(false);
        }
      }
    };

    void load();

    return () => {
      controller.abort();
      if (retryTimer !== undefined) {
        window.clearTimeout(retryTimer);
      }
    };
  }, [filters, page]);

  return { data, loading, error };
};
