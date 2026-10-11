# Optional Identity account export

Identity can include its actual configured Keycloak account projection in the
signed, paginated Privacy archive. The feature defaults to disabled. Disabled
archives identify `external_identity_unavailable` and remain incomplete. Enabling
it requires both the Privacy capability configuration and the Identity provider;
an unavailable enabled source returns 503 and must not produce a complete archive.

`KeycloakIdentityExport(settings).records(subject)` returns stable, sorted
`{table, key, data}` records. `keycloak_account` contains the requested account's
ID, username, email, first/last name, account/email state, creation timestamp and
only explicitly configured custom attributes. `keycloak_credential_metadata`
contains credential ID, type, user label and creation timestamp. Credentials'
values, secretData, credentialData, passwords, tokens, federation references,
groups, access permissions and other users are excluded. This is the declared
account/profile and credential-metadata projection, not an export of the whole
Keycloak database. Unknown custom attributes require an operator allowlist;
security-sensitive attribute names cannot be enabled.

The adapter uses the documented [Keycloak Admin REST API](https://www.keycloak.org/docs-api/26.7.5/rest-api/)
account and credential endpoints and obtains a service-account bearer token from
the [OIDC token endpoint](https://www.keycloak.org/securing-apps/oidc-layers).
Provision a dedicated viewing service account in the fixed configured realm,
with no admin write roles. Provider requests fetch only `/users/{subject UUID}`
and its `/credentials` resource; there is no user search or provider pagination.
The response account ID must equal the requested UUID. Request text cannot change
origin, realm or target paths.

Configuration fields are `identity_export_enabled`, `identity_export_origin`,
`identity_export_realm`, `identity_export_client_id`, `identity_export_key_file`,
`identity_export_timeout_seconds`, `identity_export_trusted_local` and
`identity_export_attribute_names`. Root application wiring creates the provider
only for enabled Identity and attaches it to `app.state.identity_export_provider`
and the owner export engine. Construction validates configuration without reading
credentials; the first export reads a bounded private credential file. The optional
`compose.identity-export.yaml` supplies the explicit deployment configuration;
no real credential or account was contacted during implementation.

HTTPS origins are required. Plain HTTP additionally requires the explicit local
flag and a hostname of localhost, 127.0.0.1, ::1 or keycloak. Origins cannot have
credentials, paths, queries or fragments. The configured origin is deployment
trust; it never comes from a request. HTTP redirects and environment proxies are
disabled. Every response is limited to 128 KiB, timeout to 1–15 seconds, credential
metadata to 64 entries and custom attributes to 32 names and 32 bounded values per
name. Duplicate JSON keys, invalid types, ownership mismatches and oversized
responses fail closed.

Only the service bearer token is cached in memory, for at most 60 seconds and
never beyond its lifetime minus five seconds. No profile/credential source data
is cached, so generic owner revision fingerprints observe changes between pages.
An upstream 401 invalidates the token for the next request; there is no hidden
request retry. Passwords, refresh tokens and provider tokens are never export
records. Fresh Privacy authorization and cursor/revision binding remain the
signed owner export protocol's responsibility on every page.

Verification: `tests/services/identity/test_identity_export.py` uses fake HTTP and temporary fake
credentials. It covers lazy configuration, fixed paths, UUID ownership, credential
redaction, token expiry/401, transport failures, duplicate JSON, input limits and
changed source data. No live provider calls or account corrections are performed.
