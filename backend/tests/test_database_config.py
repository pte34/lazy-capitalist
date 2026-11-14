import pytest
from pydantic import ValidationError

from app.config import Settings


@pytest.mark.parametrize(
    "options",
    [
        {"database_mode": "postgres", "artifact_dir": "work/videos", "api_token": "x" * 40},
        {
            "database_mode": "postgres",
            "database_url": "postgresql://example.invalid/db",
            "api_token": "x" * 40,
        },
        {"database_mode": "sqlite", "database_url": "postgresql://example.invalid/db"},
    ],
)
def test_explicit_database_configuration_fails_closed(options):
    with pytest.raises(ValidationError):
        Settings(**options, _env_file=None)
