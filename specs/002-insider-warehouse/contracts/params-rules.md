# Contract: `rules` Section of `config/params.yaml`

Extends [../../001-skeleton-sec-ingest/contracts/params-schema.md](../../001-skeleton-sec-ingest/contracts/params-schema.md). The file gains a fourth section, `rules`, for **research rules that are not numeric Appendix E rows but that the `prereg-v1` tag locks**.

```yaml
rules:
  # Production gates (plan §6.2); applied case-insensitively; initial values = provisional.*
  gate_common_title_regex: '…'
  gate_excluded_title_regex: '…'
  gate_plan_footnote_regex: '…'
  gate_offering_footnote_regex: '…'
  # Roles (plan §6.3)
  role_ceo_cfo_title_regex: '…'
  # Preliminary events only (plan §6.4; ≈ 63 sessions). Final events use registered.cooldown in sessions.
  prelim_cooldown_calendar_days: 91

ops:
  # added
  sec_header_target_requests_per_second: 8
  sec_headers_url_pattern: "https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/{acc}-index-headers.html"
```

## Rules checked by tests

1. **Sections**: `load_params` accepts exactly the sections `registered`, `ops`, `rules` and `provisional`, and a key may appear in only one of them.
2. **Register blocks**: `rules` entries carry no `register` block (`check_register` covers `rules` as it does `ops` and `provisional`).
3. **Regexes**: every `*_regex` in `rules` compiles case-insensitively, in Python and in DuckDB (RE2).
4. **Rate**: `ops.sec_header_target_requests_per_second ≤ ops.sec_max_requests_per_second ≤ 10`.
5. **Version**: `version` is bumped to 5 (then to 6 by D46, which raised `registered.g6_min_value` to $25,000).

## Change policy

Before `prereg-v1`, edits are free with a version bump. After the tag, a change to `rules` counts as a change to the research design: it must be logged in the plan's decision log and disclosed in the report, the same as a `registered` change.
