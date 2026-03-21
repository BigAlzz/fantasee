"use client";

import React, { createContext, useContext, useState, useEffect } from "react";

type Theme = "dark" | "sepia" | "light";

interface ThemeContextType {
  theme: Theme;
  setTheme: (theme: Theme) => void;
  toggleTheme: () => void;
}

const ThemeContext = createContext<ThemeContextType | undefined>(undefined);

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setTheme] = useState<Theme>("dark");

  // Load theme from localStorage on mount
  useEffect(() => {
    const savedTheme = localStorage.getItem("fantasee-theme") as Theme;
    if (savedTheme && ["dark", "sepia", "light"].includes(savedTheme)) {
      setTheme(savedTheme);
    }
  }, []);

  // Save theme to localStorage when it changes
  useEffect(() => {
    localStorage.setItem("fantasee-theme", theme);
    // Apply basic background color to body for smooth transitions
    if (theme === "dark") document.body.style.backgroundColor = "#09090b";
    else if (theme === "sepia") document.body.style.backgroundColor = "#f4ecd8";
    else if (theme === "light") document.body.style.backgroundColor = "#ffffff";
  }, [theme]);

  const toggleTheme = () => {
    setTheme((prev) => (prev === "dark" ? "sepia" : prev === "sepia" ? "light" : "dark"));
  };

  return (
    <ThemeContext.Provider value={{ theme, setTheme, toggleTheme }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  const context = useContext(ThemeContext);
  if (context === undefined) {
    throw new Error("useTheme must be used within a ThemeProvider");
  }
  return context;
}
