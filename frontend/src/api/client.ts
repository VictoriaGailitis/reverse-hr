import type {
  Acceptance,
  Invitation,
  Consent,
  ConsentCommand,
  ContactGrant,
  Deletion,
  Membership,
  MembershipCommand,
  Organization,
  OrganizationCommand,
  Profile,
  ProfileUpdate,
} from "./types";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    public traceId?: string,
    public fields: string[] = [],
  ) {
    super(code);
  }
}

export function errorMessage(error: unknown): string {
  if (!(error instanceof ApiError))
    return "Не удалось выполнить запрос. Повторите попытку.";
  const messages: Record<number, string> = {
    0: "Сервер недоступен или не ответил вовремя. Проверьте подключение и повторите запрос.",
    401: "Сессия истекла. Войдите снова; несохранённая форма остаётся открытой.",
    403: "Нет доступа. Проверьте роль, подтверждение email и требуемое MFA.",
    404: "Объект не найден или больше недоступен.",
    409: "Данные изменились или действие недоступно. Обновите состояние с сервера перед повтором.",
    422: "Проверьте заполнение полей.",
    503: "Сервис временно недоступен. Действие не подтверждено; попробуйте повторить.",
  };
  const message =
    messages[error.status] ??
    "Сервер отклонил запрос. Действие не подтверждено.";
  return error.traceId ? `${message} Код обращения: ${error.traceId}` : message;
}

export type Service =
  | "candidate"
  | "privacy"
  | "employer"
  | "hiring"
  | "matching"
  | "notification"
  | "integration"
  | "demo-ats"
  | "assessment"
  | "coding-workspace"
  | "code-runner"
  | "evaluation"
  | "media"
  | "whiteboard"
  | "proctoring"
  | "achievements"
  | "audit";
type TokenProvider = () => Promise<string>;

/** A failed command keeps its key. Repeating the same intent never creates a new key. */
export class BackendApi {
  private commands = new Map<string, { fingerprint: string; key: string }>();
  constructor(
    private token: TokenProvider,
    private expire: () => void,
    private base = import.meta.env.VITE_API_BASE_URL || "/api",
  ) {}

  async request<T>(
    service: Service,
    path: string,
    options: {
      method?: "GET" | "POST" | "PUT" | "DELETE";
      body?: unknown;
      version?: number;
      intent?: string;
      key?: string;
      signal?: AbortSignal;
      response?: "blob";
    } = {},
  ): Promise<T> {
    const method = options.method ?? "GET";
    const headers: Record<string, string> = { Accept: "application/json" };
    if (options.body !== undefined)
      headers["Content-Type"] =
        options.body instanceof Blob ? options.body.type : "application/json";
    if (options.version !== undefined)
      headers["If-Match"] = `"${options.version}"`;
    if (options.intent) {
      const fingerprint = JSON.stringify([
        service,
        path,
        method,
        options.body,
        options.version,
      ]);
      let command = this.commands.get(options.intent);
      if (!command || command.fingerprint !== fingerprint) {
        command = { fingerprint, key: crypto.randomUUID() };
        this.commands.set(options.intent, command);
      }
      headers["Idempotency-Key"] = command.key;
    }
    if (options.key) headers["Idempotency-Key"] = options.key;
    try {
      headers.Authorization = `Bearer ${await this.token()}`;
    } catch {
      throw new ApiError(401, "session_expired");
    }
    const timeout = AbortSignal.timeout(15000);
    const signal = options.signal
      ? AbortSignal.any([options.signal, timeout])
      : timeout;
    let response: Response;
    try {
      response = await fetch(
        `${this.base.replace(/\/$/, "")}/${service}${path}`,
        {
          method,
          headers,
          signal,
          cache: "no-store",
          credentials: "omit",
          body:
            options.body === undefined
              ? undefined
              : options.body instanceof Blob
                ? options.body
                : JSON.stringify(options.body),
        },
      );
    } catch (error) {
      if (options.signal?.aborted) throw error;
      throw new ApiError(0, "network_error");
    }
    if (response.ok && options.response === "blob")
      return (await response.blob()) as T;
    const body = await response.json().catch(() => null);
    if (!response.ok) {
      if (response.status === 401) this.expire();
      throw new ApiError(
        response.status,
        typeof body?.code === "string" ? body.code : "request_failed",
        typeof body?.trace_id === "string" ? body.trace_id : undefined,
        Array.isArray(body?.fields)
          ? body.fields.filter((field: unknown) => typeof field === "string")
          : [],
      );
    }
    if (body === null) throw new ApiError(502, "invalid_response");
    if (options.intent) this.commands.delete(options.intent);
    return body as T;
  }

  invitations(after?: string, signal?: AbortSignal) {
    return this.request<Invitation[]>(
      "hiring",
      `/v1/invitations${after ? `?after=${encodeURIComponent(after)}` : ""}`,
      { signal },
    );
  }
  invitation(id: string, signal?: AbortSignal) {
    return this.request<Invitation>(
      "hiring",
      `/v1/invitations/${encodeURIComponent(id)}`,
      { signal },
    );
  }
  acceptInvitation(invitation: Invitation, body: Acceptance) {
    return this.request<Invitation>(
      "hiring",
      `/v1/invitations/${invitation.invitation_id}/accept`,
      {
        method: "POST",
        body,
        version: invitation.version,
        intent: `accept:${invitation.invitation_id}`,
      },
    );
  }
  declineInvitation(invitation: Invitation) {
    return this.request<Invitation>(
      "hiring",
      `/v1/invitations/${invitation.invitation_id}/decline`,
      {
        method: "POST",
        version: invitation.version,
        intent: `decline:${invitation.invitation_id}`,
      },
    );
  }
  profile(signal?: AbortSignal) {
    return this.request<Profile>("candidate", "/v1/candidates/me", { signal });
  }
  saveProfile(body: ProfileUpdate, version?: number) {
    return this.request<Profile>("candidate", "/v1/candidates/me", {
      method: version ? "PUT" : "POST",
      body,
      version,
      intent: "save-profile",
    });
  }
  policies(signal?: AbortSignal) {
    return this.request<Record<string, string>>(
      "privacy",
      "/v1/consents/policies",
      { signal },
    );
  }
  consents(signal?: AbortSignal) {
    return this.request<Consent[]>("privacy", "/v1/consents", { signal });
  }
  consent(body: ConsentCommand) {
    return this.request<Consent>("privacy", "/v1/consents", {
      method: "POST",
      body,
      intent: `consent:${body.purpose}`,
    });
  }
  revokeConsent(consent: Consent) {
    return this.request<Consent>(
      "privacy",
      `/v1/consents/${consent.consent_id}/revoke`,
      {
        method: "POST",
        version: consent.version,
        intent: `revoke-consent:${consent.consent_id}`,
      },
    );
  }
  grants(signal?: AbortSignal) {
    return this.request<ContactGrant[]>("privacy", "/v1/contact-grants", {
      signal,
    });
  }
  revokeGrant(grant: ContactGrant) {
    return this.request<ContactGrant>(
      "privacy",
      `/v1/contact-grants/${grant.grant_id}/revoke`,
      {
        method: "POST",
        version: grant.version,
        intent: `revoke-grant:${grant.grant_id}`,
      },
    );
  }
  deletion(signal?: AbortSignal) {
    return this.request<Deletion>("privacy", "/v1/deletion-requests/me", {
      signal,
    });
  }
  requestDeletion() {
    return this.request<Deletion>("privacy", "/v1/deletion-requests", {
      method: "POST",
      intent: "deletion",
    });
  }
  organizations(signal?: AbortSignal) {
    return this.request<Organization[]>("employer", "/v1/organizations", {
      signal,
    });
  }
  createOrganization(body: OrganizationCommand) {
    return this.request<Organization>("employer", "/v1/organizations", {
      method: "POST",
      body,
      intent: "create-organization",
    });
  }
  members(id: string, signal?: AbortSignal) {
    return this.request<Membership[]>(
      "employer",
      `/v1/organizations/${encodeURIComponent(id)}/members`,
      { signal },
    );
  }
  addMember(org: Organization, body: MembershipCommand) {
    return this.request<Membership>(
      "employer",
      `/v1/organizations/${org.organization_id}/members`,
      {
        method: "POST",
        body,
        version: org.version,
        intent: `member:${org.organization_id}:${body.subject}`,
      },
    );
  }
}
