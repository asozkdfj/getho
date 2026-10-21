/** Colour theme: "system" follows the OS; light/dark are stored in localStorage
 * and applied as data-theme on <html> (THEME_SCRIPT runs before the first paint). */

export type Theme = "system" | "light" | "dark";

export const THEME_KEY = "edge-theme";
export const THEME_LABEL: Record<Theme, string> = {
  system: "시스템 설정",
  light: "라이트",
  dark: "다크",
};

const ORDER: Theme[] = ["system", "light", "dark"];

export function nextTheme(current: Theme): Theme {
  return ORDER[(ORDER.indexOf(current) + 1) % ORDER.length]!;
}

function valid(value: string | null | undefined): Theme {
  return value === "light" || value === "dark" ? value : "system";
}

/** The theme on screen: data-theme on <html> is the source of truth, so the
 * switch keeps cycling even when storage is blocked. */
export function readTheme(): Theme {
  return valid(document.documentElement.getAttribute("data-theme"));
}

function render(theme: Theme): void {
  const root = document.documentElement;
  if (theme === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", theme);
}

const listeners = new Set<() => void>();

/** A change made in another tab: apply the stored choice here too. */
function onStorage(event?: { key: string | null }): void {
  if (event && event.key !== null && event.key !== THEME_KEY) return;
  let stored: Theme;
  try {
    stored = valid(window.localStorage.getItem(THEME_KEY));
  } catch {
    return; // storage unreadable: keep what this page shows
  }
  render(stored);
  listeners.forEach((l) => l());
}

/** For useSyncExternalStore: notified when the theme changes here or in another tab. */
export function subscribeTheme(listener: () => void): () => void {
  if (listeners.size === 0) window.addEventListener("storage", onStorage);
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0) window.removeEventListener("storage", onStorage);
  };
}

export function applyTheme(theme: Theme): void {
  render(theme);
  try {
    if (theme === "system") window.localStorage.removeItem(THEME_KEY);
    else window.localStorage.setItem(THEME_KEY, theme);
  } catch {
    /* storage unavailable (private mode): the choice lasts for this page only */
  }
  listeners.forEach((l) => l());
}

/** Inline in <head>: applies a stored theme before anything is painted. */
export const THEME_SCRIPT = `(function(){try{var t=localStorage.getItem("${THEME_KEY}");if(t==="light"||t==="dark")document.documentElement.setAttribute("data-theme",t)}catch(e){}})()`;
