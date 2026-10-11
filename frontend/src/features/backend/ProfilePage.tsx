import { ProfileExtras } from "./ProfileExtras";
import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import type { Grade, Profile } from "../../api/types";
import { errorMessage } from "../../api/client";
import { useBackend } from "../../state/BackendContext";
import { Button } from "../../components/Button";
import { missingAsNull, ResourceError, useResource } from "./Resource";

const grades: Grade[] = ["junior", "middle", "senior", "lead"];
function ProfileForm({ initial }: { initial: Profile | null }) {
  const { api, session } = useBackend();
  const [profile, setProfile] = useState(initial);
  const [name, setName] = useState(initial?.display_name ?? "");
  const [specialization, setSpecialization] = useState(
    initial?.specialization ?? "",
  );
  const [grade, setGrade] = useState<Grade>(
    initial?.declared_grade ?? "junior",
  );
  const [additional, setAdditional] = useState(
    () => initial?.additional_specializations ?? [],
  );
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState<unknown>();
  const [reloadBusy, setReloadBusy] = useState(false);
  async function save(event: FormEvent) {
    event.preventDefault();
    if (busy || session.status !== "authenticated") return;
    setBusy(true);
    setError(undefined);
    setNotice("");
    try {
      const saved = await api.saveProfile(
        {
          display_name: name.trim(),
          specialization: specialization.trim(),
          declared_grade: grade,
          additional_specializations: additional.map((item) => ({
            specialization: item.specialization.trim(),
            declared_grade: item.declared_grade,
          })),
        },
        profile?.version,
      );
      setProfile(saved);
      setName(saved.display_name);
      setSpecialization(saved.specialization);
      setGrade(saved.declared_grade);
      setAdditional(saved.additional_specializations ?? []);
      setNotice(`Профиль сохранён на сервере · версия ${saved.version}`);
    } catch (next) {
      setError(next);
    } finally {
      setBusy(false);
    }
  }
  async function refresh() {
    if (reloadBusy) return;
    setReloadBusy(true);
    try {
      // Refresh the optimistic version, retaining the user's draft for a deliberate retry.
      setProfile(await missingAsNull(api.profile()));
      setError(undefined);
      setNotice(
        "Версия обновлена с сервера. Ваши правки сохранены в форме; проверьте их перед повторной отправкой.",
      );
    } catch (next) {
      setError(next);
    } finally {
      setReloadBusy(false);
    }
  }
  return (
    <>
      <form
        className="api-card api-form"
        onSubmit={(event) => void save(event)}
      >
        <h2>{profile ? "Ваш профиль" : "Создать профиль"}</h2>
        <label className="form-field">
          <span>Имя для отображения</span>
          <input
            required
            maxLength={100}
            value={name}
            onChange={(event) => setName(event.target.value)}
            autoComplete="name"
          />
        </label>
        <label className="form-field">
          <span>Специализация</span>
          <input
            required
            maxLength={100}
            value={specialization}
            onChange={(event) => setSpecialization(event.target.value)}
          />
        </label>
        <label className="form-field">
          <span>Заявленный уровень</span>
          <select
            value={grade}
            onChange={(event) => setGrade(event.target.value as Grade)}
          >
            {grades.map((value) => (
              <option key={value}>{value}</option>
            ))}
          </select>
        </label>
        <p>
          Подтверждённый уровень:{" "}
          {profile?.confirmed_grade ?? "ещё не подтверждён"}
        </p>
        <p className="api-muted">Каждое направление подтверждается отдельно. Можно добавить ещё девять специализаций.</p>
        {additional.map((item, index) => (
          <fieldset key={index}>
            <legend>Дополнительное направление {index + 1}</legend>
            <label className="form-field">
              <span>Специализация</span>
              <input required maxLength={100} value={item.specialization}
                onChange={(event) => setAdditional((rows) => rows.map((row, position) =>
                  position === index ? { ...row, specialization: event.target.value } : row))} />
            </label>
            <label className="form-field">
              <span>Заявленный уровень</span>
              <select value={item.declared_grade}
                onChange={(event) => setAdditional((rows) => rows.map((row, position) =>
                  position === index ? { ...row, declared_grade: event.target.value as Grade } : row))}>
                {grades.map((value) => <option key={value}>{value}</option>)}
              </select>
            </label>
            <p>Подтверждённый уровень: {profile?.specializations?.find((row) =>
              row.specialization === item.specialization)?.confirmed_grade ?? "ещё не подтверждён"}</p>
            <Button type="button" variant="secondary" disabled={busy}
              onClick={() => setAdditional((rows) => rows.filter((_, position) => position !== index))}>
              Удалить направление
            </Button>
          </fieldset>
        ))}
        <Button type="button" variant="secondary" disabled={busy || additional.length >= 9}
          onClick={() => setAdditional((rows) => [...rows, { specialization: "", declared_grade: "junior" }])}>
          Добавить специализацию
        </Button>
        {profile && (
          <p className="api-muted">Версия профиля: {profile.version}</p>
        )}
        <Button
          type="submit"
          disabled={busy || session.status !== "authenticated" || !!error}
        >
          {busy ? "Сохраняем…" : "Сохранить профиль"}
        </Button>
        {notice && <p role="status">{notice}</p>}
        {error !== undefined && (
          <div role="alert">
            <p>{errorMessage(error)}</p>
            <Button
              variant="secondary"
              disabled={reloadBusy || session.status !== "authenticated"}
              onClick={() => void refresh()}
            >
              {reloadBusy ? "Обновляем…" : "Обновить версию, сохранив правки"}
            </Button>
          </div>
        )}
      </form>
      <ProfileExtras />
      <Link className="button button-secondary" to="/candidate/privacy">
        Согласия и приватность
      </Link>
    </>
  );
}

export function ProfilePage() {
  const { api } = useBackend();
  const resource = useResource((signal) => missingAsNull(api.profile(signal)));
  return (
    <div className="screen-form">
      <h1>Профиль и резюме</h1>
      <p>Ваш профиль на сервере</p>
      {resource.status === "loading" && <p role="status">Загружаем профиль…</p>}
      {resource.status === "error" && (
        <ResourceError error={resource.error} retry={resource.reload} />
      )}
      {resource.status === "ready" && (
        <ProfileForm initial={resource.data ?? null} />
      )}
    </div>
  );
}
