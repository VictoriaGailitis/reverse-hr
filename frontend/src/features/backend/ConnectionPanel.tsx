import { useState } from "react";
import { initializeSession, login, logout } from "../../auth/session";
import { useBackend } from "../../state/BackendContext";
import { Button } from "../../components/Button";

export function ConnectionPanel() {
  const { mode, setMode, session } = useBackend();
  const [open, setOpen] = useState(false);
  return (
    <div className="connection-control">
      <button
        type="button"
        className="connection-toggle"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
      >
        Подключение · {mode === "api" ? "API" : "Демо"}
      </button>
      {open && (
        <section
          className="connection-panel"
          aria-label="Подключение к серверу"
        >
          <h2>Подключение</h2>
          <label className="form-field">
            <span>Источник данных</span>
            <select
              value={mode}
              onChange={(event) =>
                setMode(event.target.value as "api" | "demo")
              }
            >
              <option value="demo">Локальная демонстрация</option>
              <option value="api">Сервер Reverse HR</option>
            </select>
          </label>
          {mode === "api" && (
            <>
              <p>
                {session.status === "authenticated"
                  ? `Выполнен вход: ${session.name}`
                  : session.status === "loading"
                    ? "Подключаем сервер входа…"
                    : session.status === "expired"
                      ? "Сессия истекла. Войдите снова."
                      : (session.error ??
                        "Войдите через Keycloak, чтобы открыть данные сервера.")}
              </p>
              {session.status === "authenticated" ? (
                <Button variant="secondary" onClick={() => void logout()}>
                  Выйти
                </Button>
              ) : (
                <Button
                  disabled={session.status === "loading"}
                  onClick={() =>
                    void (session.status === "error"
                      ? initializeSession()
                      : login())
                  }
                >
                  {session.status === "error"
                    ? "Повторить подключение"
                    : "Войти через Keycloak"}
                </Button>
              )}
            </>
          )}
          <button
            className="text-button"
            type="button"
            onClick={() => setOpen(false)}
          >
            Закрыть
          </button>
        </section>
      )}
    </div>
  );
}
