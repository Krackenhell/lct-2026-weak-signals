import React, { useEffect, useState } from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Link, NavLink, Route, Routes, useLocation } from "react-router-dom";
import "@fontsource/unbounded/cyrillic-500.css";
import "@fontsource/unbounded/cyrillic-600.css";
import "@fontsource/unbounded/cyrillic-700.css";
import "@fontsource/unbounded/latin-500.css";
import "@fontsource/unbounded/latin-600.css";
import "@fontsource/unbounded/latin-700.css";
import "@fontsource/golos-text/cyrillic-400.css";
import "@fontsource/golos-text/cyrillic-500.css";
import "@fontsource/golos-text/cyrillic-600.css";
import "@fontsource/golos-text/latin-400.css";
import "@fontsource/golos-text/latin-500.css";
import "@fontsource/golos-text/latin-600.css";
import "@fontsource/jetbrains-mono/cyrillic-400.css";
import "@fontsource/jetbrains-mono/cyrillic-600.css";
import "@fontsource/jetbrains-mono/latin-400.css";
import "@fontsource/jetbrains-mono/latin-600.css";
import "./styles.css";
import Home from "./pages/Home";
import RunPage from "./pages/RunPage";
import Insight from "./pages/Insight";
import Methodology from "./pages/Methodology";
import Subscriptions from "./pages/Subscriptions";

export function Logo({ size = 30 }: { size?: number }) {
  return (
    <svg viewBox="0 0 32 32" width={size} height={size} aria-hidden>
      <circle cx="16" cy="16" r="15" fill="none" stroke="currentColor" strokeWidth="1.5" />
      <circle cx="16" cy="16" r="9.5" fill="none" stroke="currentColor" strokeWidth="1" opacity=".55" />
      <circle cx="16" cy="16" r="4" fill="none" stroke="currentColor" strokeWidth="1" opacity=".35" />
      <path d="M16 16 L16 1 A15 15 0 0 1 29.7 9.9 Z" fill="currentColor" opacity=".14" />
      <line x1="16" y1="16" x2="29.7" y2="9.9" stroke="currentColor" strokeWidth="1.5" />
      <circle className="blip" cx="23" cy="8.6" r="2.6" />
    </svg>
  );
}

type Theme = "light" | "dark" | "auto";

function readTheme(): Theme {
  try {
    const t = localStorage.getItem("theme");
    return t === "light" || t === "dark" ? t : "auto";
  } catch {
    return "auto";
  }
}

function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(readTheme);
  useEffect(() => {
    const root = document.documentElement;
    if (theme === "auto") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", theme);
    try {
      if (theme === "auto") localStorage.removeItem("theme");
      else localStorage.setItem("theme", theme);
    } catch {
      /* хранилище недоступно — тема просто не запоминается */
    }
  }, [theme]);
  const next: Record<Theme, Theme> = { auto: "dark", dark: "light", light: "auto" };
  const label: Record<Theme, string> = { auto: "авто", dark: "тёмная", light: "светлая" };
  return (
    <button type="button" className="theme-toggle" onClick={() => setTheme(next[theme])} title="Тема оформления">
      ◐ {label[theme]}
    </button>
  );
}

function ScrollTop() {
  const { pathname } = useLocation();
  useEffect(() => window.scrollTo(0, 0), [pathname]);
  return null;
}

function Layout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <ScrollTop />
      <header className="topbar">
        <Link to="/" className="brand" aria-label="Радар слабых сигналов — на главную">
          <span className="logo"><Logo /></span>
          <span className="brand-word">
            <b>Радар</b>
            <span>слабых сигналов</span>
          </span>
        </Link>
        <nav>
          <NavLink to="/" end>Поиск</NavLink>
          <NavLink to="/subscriptions">Подписки</NavLink>
          <NavLink to="/methodology">Методология</NavLink>
          <ThemeToggle />
        </nav>
      </header>
      <main className="container">{children}</main>
      <footer className="footer">
        <span>Агенты Москвы · ЛЦТ 2026 · задача Газпромбанк.Тех</span>
        <span>Решение «сигнал / не сигнал» — собственный классификатор</span>
      </footer>
    </>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <Layout>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/runs/:id" element={<RunPage />} />
          <Route path="/insight/:id" element={<Insight />} />
          <Route path="/methodology" element={<Methodology />} />
          <Route path="/subscriptions" element={<Subscriptions />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  </React.StrictMode>
);
