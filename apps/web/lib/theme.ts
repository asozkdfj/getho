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

export function readTheme(): Theme {
  try {
    const t = window.localStorage.getItem(THEME_KEY);
    return t === "light" || t === "dark" ? t : "system";
  } catch {
    return "system";
  }
}

const listeners = new Set<() => void>();

/** For useSyncExternalStore: notified when the theme changes here or in another tab. */
export function subscribeTheme(listener: () => void): () => void {
  listeners.add(listener);
  window.addEventListener("storage", listener);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", listener);
  };
}

export function applyTheme(theme: Theme): void {
  const root = document.documentElement;
  if (theme === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", theme);
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
