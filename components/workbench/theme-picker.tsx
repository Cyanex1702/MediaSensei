"use client";
import { useEffect, useState } from "react";
export const themes = [
  ["forest", "Forest · original"],
  ["spectrum", "Spectrum · colorful"],
  ["charcoal", "Charcoal · dark"],
  ["beige", "Beige · light"],
] as const;
export function ThemePicker() {
  const [theme, setTheme] = useState("forest");
  useEffect(() => {
    const saved = localStorage.getItem("sensei.theme");
    if (themes.some(([id]) => id === saved)) {
      setTheme(saved!);
      document.documentElement.dataset.theme = saved!;
    }
  }, []);
  return (
    <label className="theme-picker">
      <span>Theme</span>
      <select
        aria-label="Color scheme"
        value={theme}
        onChange={(e) => {
          setTheme(e.target.value);
          document.documentElement.dataset.theme = e.target.value;
          localStorage.setItem("sensei.theme", e.target.value);
        }}
      >
        {themes.map(([id, name]) => (
          <option key={id} value={id}>
            {name}
          </option>
        ))}
      </select>
    </label>
  );
}
