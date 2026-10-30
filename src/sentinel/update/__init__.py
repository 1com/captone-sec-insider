"""The daily update (specs/001-daily-data-refresh): `run` fetches what is new, stages it, rebuilds
the layers above staging and publishes; `record` keeps each run's record in schema `ops`; `verify`
checks the result against a full rebuild; `schedule` runs it on weekday evenings."""
