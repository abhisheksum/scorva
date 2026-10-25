import pytest
from apps.api.config import Settings


def test_settings_defaults():
    settings = Settings()
    assert settings.PORT == 8000
    assert settings.API_V1_PREFIX == "/api/v1"
    assert isinstance(settings.CORS_ORIGINS, list)
    assert len(settings.CORS_ORIGINS) >= 1


def test_cors_origins_parsing():
    settings = Settings(CORS_ORIGINS="http://test.com, https://test.com")
    assert settings.CORS_ORIGINS == ["http://test.com", "https://test.com"]

    json_settings = Settings(CORS_ORIGINS='["http://alpha.com", "http://beta.com"]')
    assert json_settings.CORS_ORIGINS == ["http://alpha.com", "http://beta.com"]
