import argparse
from pathlib import Path

from alembic import command
from alembic.config import Config

from reverse_hr.settings import Settings


def migration_config(settings: Settings | None = None) -> Config:
    settings = settings or Settings()
    config = Config("alembic.ini")
    locations = ["migrations/versions"]
    domain = Path("migrations/domains") / settings.service_name
    if domain.is_dir():
        locations.append(str(domain))
    config.set_main_option("version_locations", " ".join(locations))
    config.set_main_option("path_separator", "space")
    config.attributes["settings"] = settings
    return config


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["upgrade", "downgrade"])
    parser.add_argument("revision")
    args = parser.parse_args()
    getattr(command, args.action)(migration_config(), args.revision)


if __name__ == "__main__":
    main()
