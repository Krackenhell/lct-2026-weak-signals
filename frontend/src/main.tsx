import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Link, NavLink, Route, Routes } from "react-router-dom";
import "./styles.css";
import Home from "./pages/Home";
import RunPage from "./pages/RunPage";
import Insight from "./pages/Insight";
import Methodology from "./pages/Methodology";

function Layout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <header className="topbar">
        <Link to="/" className="brand">
          <span className="logo" aria-hidden>
            <svg viewBox="0 0 32 32" width="28" height="28">
              <circle cx="16" cy="16" r="14" fill="var(--accent)" />
              <circle cx="16" cy="16" r="8" fill="none" stroke="#fff" strokeWidth="2" />
              <circle cx="21" cy="11" r="2.5" fill="#fff" />
            </svg>
          </span>
          Радар слабых сигналов
        </Link>
        <nav>
          <NavLink to="/" end>Поиск</NavLink>
          <NavLink to="/methodology">Методология и качество</NavLink>
        </nav>
      </header>
      <main className="container">{children}</main>
      <footer className="footer">ЛЦТ 2026 · задача Газпромбанк.Тех · прототип</footer>
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
        </Routes>
      </Layout>
    </BrowserRouter>
  </React.StrictMode>
);
