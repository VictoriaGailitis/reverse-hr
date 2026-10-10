import { lazy, Suspense, useEffect } from "react";
import { Link, useLocation } from "react-router-dom";
import { screenByRoute } from "./design/catalog";
import { AppShell } from "./components/AppShell";
import { DesignContent } from "./components/DesignContent";
import { ScreenDirectory } from "./components/ScreenDirectory";
import { useBackend } from "./state/BackendContext";
const BackendScreens = lazy(() =>
  import("./features/backend/BackendScreens").then((module) => ({
    default: module.BackendScreens,
  })),
);
const AuthCallback = lazy(() =>
  import("./features/backend/BackendScreens").then((module) => ({
    default: module.AuthCallback,
  })),
);

export function App() {
  const location = useLocation();
  const { mode } = useBackend();
  const screen = screenByRoute.get(location.pathname + location.hash);
  useEffect(() => {
    document.title = screen
      ? `${screen.name.replace(/^\d+ · /, "")} — ФСП`
      : "Экран не найден — ФСП";
  }, [screen]);
  if (location.pathname === "/auth/callback")
    return (
      <Suspense fallback={<p role="status">Загрузка…</p>}>
        <AuthCallback />
      </Suspense>
    );
  if (!screen)
    return (
      <main className="not-found">
        <h1>Экран не найден</h1>
        <p>Этот маршрут пока отсутствует в прототипе.</p>
        <Link className="button" to="/">
          На главную
        </Link>
        <ScreenDirectory />
      </main>
    );
  return (
    <>
      <AppShell screen={screen}>
        {mode === "api" ? (
          <Suspense fallback={<p role="status">Загрузка…</p>}>
            <BackendScreens key={screen.key} screen={screen} />
          </Suspense>
        ) : (
          <DesignContent key={screen.key} screen={screen} />
        )}
      </AppShell>
      <ScreenDirectory />
    </>
  );
}
