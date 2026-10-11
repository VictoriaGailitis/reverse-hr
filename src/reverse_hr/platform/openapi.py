"""Keep published schema IDs independent of internal service package moves."""

import re

_SERVICE_SCHEMA = re.compile(r"^reverse_hr__services__[a-z_]+__domain__")


def preserve_schema_ids(app):
    original = app.openapi

    def published_openapi():
        schema = original()
        definitions = schema.get("components", {}).get("schemas", {})
        aliases = {
            name: _SERVICE_SCHEMA.sub("reverse_hr__domains__", name)
            for name in definitions
            if _SERVICE_SCHEMA.match(name)
        }
        if not aliases:
            return schema
        if len(set(aliases.values())) != len(aliases):
            raise ValueError("Published schema IDs must be unique")
        definitions.update({aliases[name]: definitions.pop(name) for name in aliases})

        def rewrite(node):
            if isinstance(node, dict):
                ref = node.get("$ref")
                if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
                    name = ref.removeprefix("#/components/schemas/")
                    if name in aliases:
                        node["$ref"] = "#/components/schemas/" + aliases[name]
                for value in node.values():
                    rewrite(value)
            elif isinstance(node, list):
                for value in node:
                    rewrite(value)

        rewrite(schema)
        return schema

    app.openapi = published_openapi
