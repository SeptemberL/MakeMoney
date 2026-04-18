## ADDED Requirements

### Requirement: Scheduled daily Tushare sync at 17:00

The system SHALL register an APScheduler job that runs once per calendar day at 17:00 (local scheduler time unless configured otherwise) and invokes the same Tushare daily-bar sync logic used to update tracked per-stock tables.

#### Scenario: Job fires at configured time

- **WHEN** the scheduled time 17:00 is reached and the job is enabled
- **THEN** the system executes the Tushare sync entrypoint without requiring an HTTP request

#### Scenario: Job can be disabled

- **WHEN** the task entry in `configs/tasks_config.yaml` has `enabled: false`
- **THEN** the system SHALL NOT run that job on schedule

### Requirement: Unadjusted (non-rebuilt) daily bars from Tushare

The system SHALL fetch A-share daily bars via Tushare interfaces that correspond to **unadjusted** (未复权) OHLC/volume for the trade date being applied, consistent with existing `pro.daily` usage and without switching to ex-dividend-adjusted series.

#### Scenario: No intentional switch to adjusted series

- **WHEN** the scheduled sync runs
- **THEN** the implementation SHALL NOT replace or parameterize the data source to forward-/backward-adjusted daily series for this change

### Requirement: Update all tracked stock tables

The system SHALL update **every** stock in the tracked set returned by the same mechanism as the manual API (e.g. `_get_tracked_stocks()`), writing each row into that stock’s dedicated table using upsert semantics equivalent to the existing `fetch_today_tushare` behavior.

#### Scenario: Per-stock upsert

- **WHEN** Tushare returns a row for a tracked stock’s code for the resolved trade date
- **THEN** the system SHALL insert or update that row in the corresponding stock table

#### Scenario: Missing data for a tracked code

- **WHEN** Tushare has no row for a tracked stock on the resolved date
- **THEN** the system SHALL skip that stock without failing the entire job (consistent with existing skip counting behavior)

### Requirement: Shared implementation with manual API

The system SHALL implement the core sync in a callable module function and SHALL have the existing `POST /api/fetch_today_tushare` route delegate to that function so manual and scheduled paths cannot diverge.

#### Scenario: Single code path

- **WHEN** either the scheduled job or the HTTP API triggers a sync
- **THEN** both SHALL invoke the same underlying sync function

### Requirement: Configuration and failure handling

The system SHALL read the Tushare token from `config.ini` `[TUSHARE]` as today’s API does. If the token is missing or placeholder, the scheduled run SHALL log a clear message and SHALL NOT crash the scheduler thread.

#### Scenario: Missing token on scheduled run

- **WHEN** the job runs and the Tushare token is not configured
- **THEN** the system logs an error or warning and exits the job without unhandled exceptions
