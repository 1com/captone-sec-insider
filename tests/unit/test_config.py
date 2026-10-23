import logging

import pytest
import yaml

from sentinel.config import ConfigError, RedactingFilter, load_params, load_secrets, redact


def test_missing_contact_is_rejected(tmp_path):
    env = tmp_path / ".env"
    env.write_text("TIINGO_API=abcd1234\n")
    with pytest.raises(ConfigError, match="SEC_USER_AGENT"):
        load_secrets(env)


def test_contact_without_email_is_rejected(tmp_path):
    env = tmp_path / ".env"
    env.write_text('SEC_USER_AGENT="Just A Name"\n')
    with pytest.raises(ConfigError, match="e-mail"):
        load_secrets(env)


def test_email_only_contact_warns(tmp_path):
    env = tmp_path / ".env"
    env.write_text("SEC_USER_AGENT=me@example.com\n")
    assert load_secrets(env).warnings


def test_name_and_email_has_no_warning(fake_env):
    secrets = load_secrets(fake_env)
    assert secrets.sec_user_agent == "Test User test@example.com"
    assert secrets.warnings == []


def test_tiingo_key_is_redacted(fake_env, caplog):
    load_secrets(fake_env)
    assert redact("key=tiingo-secret-123 end") == "key=*** end"
    logger = logging.getLogger("redaction-test")
    logger.addFilter(RedactingFilter())
    with caplog.at_level(logging.INFO, logger="redaction-test"):
        logger.info("calling with token %s", "tiingo-secret-123")
    assert "tiingo-secret-123" not in caplog.text
    assert "***" in caplog.text


def test_key_in_two_sections_is_rejected(tmp_path, params):
    params["ops"]["cluster_window"] = 14
    path = tmp_path / "params.yaml"
    path.write_text(yaml.safe_dump(params, allow_unicode=True))
    with pytest.raises(ConfigError, match="cluster_window"):
        load_params(path)
