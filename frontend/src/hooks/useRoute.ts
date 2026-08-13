import { useCallback, useSyncExternalStore, type MouseEvent } from "react";

const getPath = () => (typeof window === "undefined" ? "/" : window.location.pathname);

const listeners = new Set<() => void>();

const subscribe = (onStoreChange: () => void) => {
  listeners.add(onStoreChange);
  window.addEventListener("popstate", onStoreChange);
  return () => {
    listeners.delete(onStoreChange);
    window.removeEventListener("popstate", onStoreChange);
  };
};

const navigate = (nextPath: string) => {
  if (nextPath === getPath()) {
    return;
  }
  window.history.pushState({}, "", nextPath);
  listeners.forEach((listener) => listener());
  window.scrollTo({ top: 0, behavior: "smooth" });
};

export const useRoute = () => {
  const path = useSyncExternalStore(subscribe, getPath, () => "/");
  return { path, navigate: useCallback(navigate, []) };
};

export const navigateLinkProps = (
  href: string,
  navigateFn: (nextPath: string) => void
) => ({
  href,
  onClick: (event: MouseEvent<HTMLAnchorElement>) => {
    if (event.defaultPrevented || event.button !== 0) {
      return;
    }
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
      return;
    }
    event.preventDefault();
    navigateFn(href);
  }
});
