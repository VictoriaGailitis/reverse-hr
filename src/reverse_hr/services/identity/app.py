from reverse_hr.platform.settings import Settings


def configure(app, config, engine):
    from reverse_hr.protocols.processing_access import ProcessingAccess

    app.state.processing_access = ProcessingAccess(config)
    if "identity" == "identity" and config.identity_export_enabled:
        from reverse_hr.services.identity.identity_export import KeycloakIdentityExport

        provider = KeycloakIdentityExport(config)
        app.state.identity_export_provider = engine.identity_export_provider = provider
    from reverse_hr.coordination.privacy_request_exchange import RightsAccess
    from reverse_hr.coordination.privacy_request_exchange import router as rights_exchange_router

    app.state.rights_access = RightsAccess(config)
    app.include_router(rights_exchange_router)


def check_ready(app, config, engine, connection):
    pass


def create_app(settings=None):
    from reverse_hr.platform.app import create_app as build_app

    config = settings or Settings(service_name="identity")
    if config.service_name != "identity":
        raise ValueError("Service entry point does not match configuration")
    return build_app(config)
