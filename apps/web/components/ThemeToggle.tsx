"use client";

import { useSyncExternalStore } from "react";

import {
  applyTheme,
  nextTheme,
  readTheme,
  subscribeTheme,
  THEME_LABEL,
  type Theme,
} from "@/lib/theme";

/** Cycles system -> light -> dark; the choice is kept in this browser only. */
export function ThemeToggle() {
  // the server renders "system"; the browser reads the stored choice
  const theme = useSyncExternalStore(subscribeTheme, readTheme, () => "system" as Theme);

  const label = `화면 테마: ${THEME_LABEL[theme]} (눌러서 바꾸기)`;
  return (
    <button
      type="button"
      className="theme-toggle"
      aria-label={label}
      title={label}
      onClick={() => {
        applyTheme(nextTheme(theme));
      }}
    >
      <Icon theme={theme} />
    </button>
  );
}

function Icon({ theme }: { theme: Theme }) {
  const common = {
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.8,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
  };
  if (theme === "light") {
    return (
      <svg {...common}>
        <circle cx="12" cy="12" r="4" />
        <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
      </svg>
    );
  }
  if (theme === "dark") {
    return (
      <svg {...common}>
        <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
      </svg>
    );
  }
  return (
    <svg {...common}>
      <rect x="3" y="4" width="18" height="12" rx="2" />
      <path d="M8 20h8M12 16v4" />
    </svg>
  );
}
