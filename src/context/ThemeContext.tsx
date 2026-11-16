'use client';

import React, { createContext, useContext, useEffect, useState } from 'react';

type Theme = 'dark' | 'light';

interface ThemeContextType {
  theme: Theme;
  toggleTheme: () => void;
}

const ThemeContext = createContext<ThemeContextType>({
  theme: 'dark',
  toggleTheme: () => {},
});

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setTheme] = useState<Theme>('dark');

  const applyTheme = (t: Theme) => {
    if (typeof document === 'undefined') return;
    if (t === 'light') {
      document.documentElement.classList.remove('dark');
      document.documentElement.classList.add('light');
      document.documentElement.setAttribute('data-theme', 'light');
      document.documentElement.style.colorScheme = 'light';
    } else {
      document.documentElement.classList.remove('light');
      document.documentElement.classList.add('dark');
      document.documentElement.setAttribute('data-theme', 'dark');
      document.documentElement.style.colorScheme = 'dark';
    }
  };

  useEffect(() => {
    let saved: string | null = null;
    try { saved = localStorage.getItem('aivolve-theme'); } catch { /* Theme still works with storage disabled. */ }
    const initialTheme: Theme = saved === 'light' ? 'light' : 'dark';
    queueMicrotask(() => {
      setTheme(initialTheme);
    });
    applyTheme(initialTheme);
  }, []);


  const toggleTheme = () => {
    setTheme((prev) => {
      const next: Theme = prev === 'dark' ? 'light' : 'dark';
      try { localStorage.setItem('aivolve-theme', next); } catch { /* Keep the in-memory preference. */ }
      applyTheme(next);
      return next;
    });
  };


  return (
    <ThemeContext.Provider value={{ theme, toggleTheme }}>
      {children}
    </ThemeContext.Provider>
  );
}

export const useTheme = () => useContext(ThemeContext);
