import { useEffect, useState } from "react";

type Theme = "system" | "light" | "dark";

const KEY = "ipo_theme";
const ORDER: Theme[] = ["system", "light", "dark"];
const ICON: Record<Theme, string> = { system: "🖥", light: "☀", dark: "🌙" };
const LABEL: Record<Theme, string> = {
  system: "Match system",
  light: "Light",
  dark: "Dark",
};

/**
 * Three-state theme control.
 *
 * "System" is the default and a real option rather than just the absence of a
 * choice — someone whose OS switches at sunset should not have to re-pick every
 * evening. The explicit states write `data-theme` on the root, which the
 * stylesheet honours over the `prefers-color-scheme` media query.
 */
export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(() => {
    try {
      const saved = localStorage.getItem(KEY) as Theme | null;
      return saved && ORDER.includes(saved) ? saved : "system";
    } catch {
      return "system";
    }
  });

  useEffect(() => {
    const root = document.documentElement;
    if (theme === "system") {
      root.removeAttribute("data-theme");
    } else {
      root.setAttribute("data-theme", theme);
    }
    try {
      localStorage.setItem(KEY, theme);
    } catch {
      /* private mode — the theme just won't persist */
    }
  }, [theme]);

  const next = ORDER[(ORDER.indexOf(theme) + 1) % ORDER.length];

  return (
    <button
      className="theme-toggle"
      onClick={() => setTheme(next)}
      title={`Theme: ${LABEL[theme]} — click for ${LABEL[next]}`}
      aria-label={`Theme: ${LABEL[theme]}. Switch to ${LABEL[next]}.`}
    >
      <span className="theme-icon">{ICON[theme]}</span>
    </button>
  );
}
