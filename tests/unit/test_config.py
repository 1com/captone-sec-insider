import logging
from datetime import date

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


def test_four_sections_in_order():
    from sentinel.config import SECTIONS

    assert SECTIONS == ("registered", "ops", "rules", "provisional")


def test_params_version_is_8(params):
    # 5: rules; 6: G6 minimum $25k (D46); 7: pilot G6 kept; 8: market data (feature 004)
    assert params["version"] == 8


def test_rules_regexes_compile_in_python_and_duckdb(params):
    import re

    import duckdb

    con = duckdb.connect()
    regexes = {k: v for k, v in params["rules"].items() if k.endswith("_regex")}
    assert len(regexes) == 5
    for key, pattern in regexes.items():
        re.compile(pattern, re.IGNORECASE)
        con.execute("select regexp_matches('x', ?, 'i')", [pattern]).fetchone()  # RE2 syntax
        assert key.startswith(("gate_", "role_"))


def test_header_rate_within_ceiling(params):
    ops = params["ops"]
    assert ops["sec_header_target_requests_per_second"] <= ops["sec_max_requests_per_second"] <= 10


def test_header_rate_above_ceiling_is_rejected(tmp_path, params):
    params["ops"]["sec_header_target_requests_per_second"] = 11
    path = tmp_path / "params.yaml"
    path.write_text(yaml.safe_dump(params, allow_unicode=True))
    with pytest.raises(ConfigError, match="header"):
        load_params(path)


def test_bad_rules_regex_is_rejected(tmp_path, params):
    params["rules"]["gate_plan_footnote_regex"] = "(unclosed"
    path = tmp_path / "params.yaml"
    path.write_text(yaml.safe_dump(params, allow_unicode=True))
    with pytest.raises(ConfigError, match="rules.gate_plan_footnote_regex"):
        load_params(path)


def test_rules_key_in_another_section_is_rejected(tmp_path, params):
    params["provisional"]["prelim_cooldown_calendar_days"] = 91
    path = tmp_path / "params.yaml"
    path.write_text(yaml.safe_dump(params, allow_unicode=True))
    with pytest.raises(ConfigError, match="prelim_cooldown_calendar_days"):
        load_params(path)


def _reload(tmp_path, params):
    path = tmp_path / "params.yaml"
    path.write_text(yaml.safe_dump(params, allow_unicode=True))
    return load_params(path)


@pytest.mark.parametrize(
    ("section", "key", "value", "message"),
    [
        ("rules", "g7_no_sic", "drop", "g7_no_sic"),
        ("rules", "g7_excluded_sic", ["6770"], "g7_excluded_sic"),
        ("rules", "final_detection_start", date(2012, 6, 1), "before"),
        ("rules", "price_history_start", date(2011, 1, 1), "a year before"),
        ("ops", "tiingo_paid_until", date(2026, 10, 1), "tiingo_paid_until"),
        ("rules", "delisting_merger_forms", ["DEFM14A", "25"], "overlap"),
    ],
)
def test_market_rules_are_checked(tmp_path, params, section, key, value, message):
    """specs/004-market-data-events/contracts/params-rules.md, rules 2–5."""
    params[section][key] = value
    with pytest.raises(ConfigError, match=message):
        _reload(tmp_path, params)


def test_market_rules_defaults(params):
    rules, ops = params["rules"], params["ops"]
    assert rules["g7_no_sic"] == "exclude"
    assert rules["g7_excluded_sic"] == [6770, 6722, 6726]
    assert rules["final_detection_start"] == date(2011, 7, 1)
    assert rules["price_history_start"] == date(2010, 1, 1)
    assert ops["tiingo_paid_from"] == date(2026, 10, 29)
    assert ops["reference_symbols"] == ["SPY", "IWM"]
    other = params["registered"]["delisting_returns"]["value"]["other_venue_treated_as"]
    assert other == "performance_nasdaq"


def test_paid_until_after_from_is_accepted(tmp_path, params):
    params["ops"]["tiingo_paid_until"] = date(2026, 11, 28)
    assert _reload(tmp_path, params)["ops"]["tiingo_paid_until"] == date(2026, 11, 28)


def test_paths_for_market_data(tmp_path):
    from sentinel.config import Paths

    paths = Paths.from_root(tmp_path)
    assert paths.yahoo == tmp_path / "data" / "raw" / "yahoo"
    assert paths.tiingo == tmp_path / "data" / "raw" / "tiingo"
    assert paths.french == tmp_path / "data" / "raw" / "french"
    assert paths.finra == tmp_path / "data" / "raw" / "finra"
    assert paths.sec_company == tmp_path / "data" / "raw" / "sec" / "company"
    assert paths.audits_004 == tmp_path / "specs" / "004-market-data-events" / "audits"
