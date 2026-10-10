import type Keycloak from "keycloak-js";

export type SessionState = {
  status:
    | "idle"
    | "loading"
    | "anonymous"
    | "authenticated"
    | "expired"
    | "error";
  name: string;
  roles?: string[];
  subject?: string;
  error?: string;
};
let state: SessionState = { status: "idle", name: "" };
let client: Keycloak | undefined;
let initialization: Promise<void> | undefined;
const listeners = new Set<() => void>();
function publish(next: SessionState) {
  state = next;
  for (const listener of listeners) listener();
}
export const subscribeSession = (listener: () => void) => {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
};
export const sessionSnapshot = () => state;

export async function initializeSession(): Promise<void> {
  if (initialization) return initialization;
  publish({ status: "loading", name: "" });
  initialization = (async () => {
    try {
      const { default: Adapter } = await import("keycloak-js");
      client = new Adapter({
        url: import.meta.env.VITE_KEYCLOAK_URL || "http://localhost:8080",
        realm: import.meta.env.VITE_KEYCLOAK_REALM || "reverse-hr",
        clientId: import.meta.env.VITE_KEYCLOAK_CLIENT_ID || "reverse-hr-web",
      });
      client.onAuthLogout = () => publish({ status: "expired", name: "" });
      client.onAuthRefreshError = expireSession;
      const authenticated = await client.init({
        flow: "standard",
        pkceMethod: "S256",
        responseMode: "query",
        checkLoginIframe: false,
        enableLogging: false,
      });
      publish({
        status: authenticated ? "authenticated" : "anonymous",
        name: authenticated ? (client.tokenParsed?.name ?? "Пользователь") : "",
        roles: authenticated ? (client.realmAccess?.roles ?? []) : [],
        subject: authenticated ? client.subject : undefined,
      });
    } catch {
      client?.clearToken();
      client = undefined;
      initialization = undefined;
      publish({
        status: "error",
        name: "",
        error:
          "Не удалось подключиться к серверу входа. Проверьте доступность Keycloak.",
      });
    }
  })();
  return initialization;
}

export async function accessToken(): Promise<string> {
  if (!client?.authenticated) throw new Error("session_expired");
  try {
    await client.updateToken(30);
    if (!client.token) throw new Error("session_expired");
    return client.token;
  } catch {
    expireSession();
    throw new Error("session_expired");
  }
}

export function expireSession() {
  client?.clearToken();
  publish({ status: "expired", name: "" });
}

export async function login(register = false) {
  await initializeSession();
  if (!client) return;
  try {
    sessionStorage.setItem(
      "fsp:return-to",
      location.pathname === "/auth/callback"
        ? "/candidate/profile"
        : location.pathname + location.search + location.hash,
    );
  } catch {
    /* Optional return path. */
  }
  const options = {
    redirectUri: `${location.origin}/auth/callback`,
    scope: "openid profile email",
  };
  try {
    if (register) await client.register(options);
    else await client.login(options);
  } catch {
    publish({
      status: "error",
      name: "",
      error: "Не удалось открыть страницу входа.",
    });
  }
}

export async function logout() {
  if (!client) return;
  try {
    await client.logout({ redirectUri: `${location.origin}/auth/callback` });
  } catch {
    expireSession();
  }
}
