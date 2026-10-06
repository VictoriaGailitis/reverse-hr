#!/bin/sh
set -eu
# Identifiers are a fixed allowlist; passwords are psql variables, not SQL interpolation.
for service in identity privacy candidate employer assessment coding_workspace code_runner whiteboard media proctoring evaluation matching hiring achievements integration notification audit keycloak; do
  key="$(echo "$service" | tr '[:lower:]' '[:upper:]')_DB_PASSWORD"
  password="$(printenv "$key")"
  test -n "$password"
  psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --set=ON_ERROR_STOP=1 \
    --set=role="$service" --set=password="$password" <<'SQL'
CREATE ROLE :"role" LOGIN PASSWORD :'password' NOSUPERUSER NOCREATEDB NOCREATEROLE;
CREATE DATABASE :"role" OWNER :"role";
REVOKE ALL ON DATABASE :"role" FROM PUBLIC;
SQL
  psql --username "$POSTGRES_USER" --dbname "$service" --set=ON_ERROR_STOP=1 \
    --set=role="$service" <<'SQL'
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT ALL ON SCHEMA public TO :"role";
SQL
done
