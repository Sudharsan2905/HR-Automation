from app._core.settings import Settings, settings


def test_sourcing_settings_defaults():
    assert settings.SOURCING_BATCH_SIZE == 5
    assert settings.SOURCING_MIN_SCORE == 60
    assert settings.SOURCING_PAGES_PER_RUN == 5
    assert settings.SOURCING_MAX_PAGE == 20
    assert settings.SOURCING_PREFETCH_PAGES == 2
    assert settings.SOURCING_SCREEN_CHUNK == 10
    assert settings.SOURCING_SCREEN_CONCURRENCY == 4
    # compare the code default, so a local .env override (e.g. 16000 for gpt-4o) doesn't matter
    assert Settings.model_fields["LLM_MAX_TOKENS_SOURCING"].default == 32000
    assert settings.SOURCING_RUN_TIMEOUT_MINUTES == 20


def test_linkedin_is_read_more_gently_than_naukri():
    assert settings.SOURCING_LINKEDIN_PAGES_PER_RUN == 4
    assert settings.SOURCING_LINKEDIN_PREFETCH_PAGES == 0   # no spare pages: each LinkedIn candidate costs a contact view
    assert settings.SOURCING_LINKEDIN_MAX_PAGE == 20
    assert settings.SOURCING_LINKEDIN_PAGES_PER_RUN <= settings.SOURCING_PAGES_PER_RUN
