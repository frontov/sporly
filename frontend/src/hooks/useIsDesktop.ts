import { useEffect, useState } from "react";

const QUERY = "(min-width: 768px)";

export const useIsDesktop = () => {
  const [isDesktop, setIsDesktop] = useState(() =>
    typeof window === "undefined" ? true : window.matchMedia(QUERY).matches
  );

  useEffect(() => {
    const mql = window.matchMedia(QUERY);
    const listener = () => setIsDesktop(window.matchMedia(QUERY).matches);
    mql.addEventListener("change", listener);
    window.addEventListener("resize", listener);
    return () => {
      mql.removeEventListener("change", listener);
      window.removeEventListener("resize", listener);
    };
  }, []);

  return isDesktop;
};
