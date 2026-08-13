import { useEffect, useState } from "react";
import { CalendarEventsResponse, CalendarFiltersState } from "../types/events";

const buildQuery = (filters: CalendarFiltersState) => {
  const params = new URLSearchParams();
  filters.cities.forEach((city) => params.append("city", city));
  filters.categories.forEach((category) => params.append("category", category));
  return params.toString();
};

const EMPTY_RESPONSE: CalendarEventsResponse = {
  items: [],
  is_loading: false,
  total: 0,
  available_cities: [],
  available_categories: []
};

export const useCalendarEvents = (filters: CalendarFiltersState) => {
  const [data, setData] = useState<CalendarEventsResponse>(EMPTY_RESPONSE);
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
        const query = buildQuery(filters);
        const response = await fetch(`/api/events/calendar${query ? `?${query}` : ""}`, {
          signal: controller.signal
        });

        if (!response.ok) {
          throw new Error(`Backend returned ${response.status}`);
        }

        const payload = (await response.json()) as CalendarEventsResponse;
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
  }, [filters]);

  return { data, loading, error };
};
