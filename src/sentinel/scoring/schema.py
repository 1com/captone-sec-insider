"""Database tables for model scores and outcomes (Layer 5)."""

import duckdb


def create_tables(con: duckdb.DuckDBPyConnection) -> None:
    """Create score and model tables if they do not already exist."""
    con.execute("create schema if not exists score")
    con.execute("create schema if not exists model")

    con.execute("""
        create table if not exists model.registry (
            question varchar not null,
            model_version varchar not null,
            algorithm varchar not null,
            training_end date not null,
            features_count integer not null,
            status varchar not null,
            registered_at timestamp not null,
            primary key (question, model_version)
        )
    """)

    con.execute("""
        create table if not exists score.daily (
            cik varchar not null,
            as_of date not null,
            question varchar not null,
            model_version varchar not null,
            forecast_val double not null,
            band integer not null,
            coverage varchar not null,
            extra_json varchar,
            scored_at timestamp not null,
            primary key (cik, as_of, question, model_version)
        )
    """)

    con.execute("""
        create table if not exists score.outcome (
            cik varchar not null,
            as_of date not null,
            question varchar not null,
            model_version varchar not null,
            window_end date not null,
            forecast_val double not null,
            forecast_band integer not null,
            actual_val double not null,
            error double not null,
            is_hit boolean not null,
            evaluated_at timestamp not null,
            primary key (cik, as_of, question, model_version)
        )
    """)
