import { expect, type Page, type Route } from "@playwright/test";

export const subject = "11111111-1111-4111-8111-111111111111";
export const orgId = "22222222-2222-4222-8222-222222222222";
export const consentId = "33333333-3333-4333-8333-333333333333";
export const grantId = "44444444-4444-4444-8444-444444444444";
export const profile = {
  candidate_id: subject,
  display_name: "Тестовый кандидат",
  specialization: "Frontend",
  declared_grade: "middle",
  confirmed_grade: null,
  version: 3,
};
export const organization = {
  organization_id: orgId,
  name: "Тестовая организация",
  verification_status: "pending",
  verification_reason: null,
  verified_by: null,
  version: 1,
};
export const policies = {
  assessment: "demo-v1",
  recording: "demo-v1",
  profile_publication: "demo-v1",
  ats_export: "demo-v1",
  contact_disclosure: "demo-v1",
};

export function jwt(payload: Record<string, unknown>) {
  return `${Buffer.from(JSON.stringify({ alg: "RS256", typ: "JWT" })).toString("base64url")}.${Buffer.from(JSON.stringify(payload)).toString("base64url")}.synthetic-signature`;
}
export async function json(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
    headers: {
      "Access-Control-Allow-Origin": "http://127.0.0.1:5175",
      "Access-Control-Allow-Credentials": "true",
    },
  });
}

/** Runs the real JS adapter against a synthetic OAuth server, never a token injection hook. */
export async function oauth(
  page: Page,
  invalidNonce = false,
  roles = ["candidate", "employer"],
) {
  let nonce = "";
  let challenge = "";
  await page.addInitScript(() =>
    sessionStorage.setItem("fsp:backend-mode", "api"),
  );
  await page.route(
    "http://localhost:8080/realms/reverse-hr/protocol/openid-connect/**",
    async (route) => {
      const url = new URL(route.request().url());
      if (url.pathname.endsWith("/auth")) {
        expect(url.searchParams.get("response_type")).toBe("code");
        expect(url.searchParams.get("code_challenge_method")).toBe("S256");
        expect(url.searchParams.get("client_id")).toBe("reverse-hr-web");
        nonce = url.searchParams.get("nonce")!;
        challenge = url.searchParams.get("code_challenge")!;
        const callback = new URL(url.searchParams.get("redirect_uri")!);
        callback.searchParams.set("code", "synthetic-code");
        callback.searchParams.set("state", url.searchParams.get("state")!);
        await route.fulfill({
          status: 302,
          headers: { Location: callback.toString() },
        });
      } else if (url.pathname.endsWith("/token")) {
        const params = new URLSearchParams(route.request().postData()!);
        const verifier = params.get("code_verifier")!;
        const { createHash } = await import("node:crypto");
        expect(createHash("sha256").update(verifier).digest("base64url")).toBe(
          challenge,
        );
        expect(params.get("grant_type")).toBe("authorization_code");
        expect(params.has("client_secret")).toBe(false);
        const common = {
          sub: subject,
          exp: Math.floor(Date.now() / 1000) + 300,
          iat: Math.floor(Date.now() / 1000),
          name: "Тестовый пользователь",
        };
        await json(route, {
          access_token: jwt({
            ...common,
            realm_access: { roles },
          }),
          refresh_token: jwt(common),
          id_token: jwt({
            ...common,
            nonce: invalidNonce ? "wrong-nonce" : nonce,
          }),
          token_type: "Bearer",
          expires_in: 300,
        });
      } else await json(route, {});
    },
  );
}

export async function login(page: Page, path = "/candidate/profile") {
  await page.goto(path);
  await page
    .getByRole("button", { name: "Войти через Keycloak", exact: true })
    .click();
  await expect(page).toHaveURL(
    (url) => url.pathname + url.search + url.hash === path,
  );
  await expect(
    page.getByText("Тестовый пользователь", { exact: true }),
  ).toBeVisible();
}
