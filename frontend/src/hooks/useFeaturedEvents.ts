import { useEffect, useState } from "react";
import { EventsResponse } from "../types/events";

const EMPTY_RESPONSE: EventsResponse = {
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
};

export const useFeaturedEvents = (page: number) => {
  const [data, setData] = useState<EventsResponse>(EMPTY_RESPONSE);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();

    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const response = await fetch(
          `/api/events/featured?page=${page}&page_size=24`,
          { signal: controller.signal }
        );
        if (!response.ok) {
          throw new Error(`Backend returned ${response.status}`);
        }
        setData((await response.json()) as EventsResponse);
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") {
          return;
        }
        setError("Не удалось загрузить рекомендованные события.");
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false);
        }
      }
    };

    void load();
    return () => controller.abort();
  }, [page]);

  return { data, loading, error };
};
