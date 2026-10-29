"""Layer 4: features, each computed as of the close of a chosen trading day (docs/architecture.md).

`feature.row` lists the (company, day) rows; each family module fills one table keyed by them
(`feature.price`, `feature.fundamental`, `feature.event`, `feature.insider`, `feature.short`,
`feature.macro`), and `feature.snapshot` joins them with the panel's row rules. Definitions are
v1's (risk_params v5 and the v1 feature list) except where `docs/decisions.md` V2-13 says.
"""
