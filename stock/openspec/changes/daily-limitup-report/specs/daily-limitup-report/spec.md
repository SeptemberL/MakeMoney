## ADDED Requirements

### Requirement: Daily limit-up report runs after market close
The system SHALL generate a daily limit-up report for a given trading date \(D\) after 17:00 local time, and SHALL support on-demand rerun for any specified trading date.

#### Scenario: Scheduled run for latest trading date
- **WHEN** the clock is after 17:00 and the scheduler triggers the job without an explicit date
- **THEN** the system determines the latest trading date \(D\) and generates the report for \(D\)

#### Scenario: Manual rerun for a specified date
- **WHEN** an operator runs the job with a specified trading date \(D\)
- **THEN** the system regenerates the report for \(D\) using the same rules and overwrites/upserts existing results for \(D\)

### Requirement: Identify the set of limit-up stocks for the day
For a trading date \(D\), the system SHALL identify the set of stocks that are considered “limit-up on day \(D\)” using end-of-day daily data.

#### Scenario: Stock closes at limit-up
- **WHEN** a stock’s end-of-day status indicates it closed at the limit-up price for date \(D\)
- **THEN** the stock is included in the report for date \(D\)

### Requirement: Compute consecutive limit-up days
For each stock included for date \(D\), the system SHALL compute the number of consecutive trading days ending at \(D\) where the stock closed limit-up.

#### Scenario: Two-day consecutive limit-up
- **WHEN** the stock closed limit-up on \(D\) and on the previous trading date \(D-1\), but did not close limit-up on \(D-2\)
- **THEN** the system outputs consecutive limit-up days as 2

### Requirement: Determine first limit-up time on the day
For each stock included for date \(D\), the system SHALL compute the first time on date \(D\) at which the stock price reaches the limit-up price (“first limit-up time”).

#### Scenario: First touch of limit-up
- **WHEN** minute-level data for date \(D\) shows the first bar where price reaches the limit-up price
- **THEN** the system outputs that bar’s timestamp as the first limit-up time

### Requirement: Determine final seal time (no reopen until close)
For each stock included for date \(D\), the system SHALL compute the “final seal time” as the timestamp of the last time the stock reaches limit-up price on date \(D\) after which it does not trade below limit-up price again until market close.

#### Scenario: Multiple reopenings then final seal
- **WHEN** a stock reaches limit-up, reopens (trades below limit-up), re-seals multiple times, and then reaches limit-up again and never trades below limit-up until close
- **THEN** the system outputs the timestamp of that last re-seal as the final seal time

### Requirement: Turnover at first limit-up time
For each stock included for date \(D\), the system SHALL output the turnover rate at the first limit-up time.

#### Scenario: Turnover available at minute-level
- **WHEN** minute-level turnover rate is available for date \(D\)
- **THEN** the system outputs the turnover rate value aligned to the first limit-up time

#### Scenario: Turnover derived from cumulative volume
- **WHEN** minute-level turnover rate is not available but cumulative traded volume and free-float shares are available
- **THEN** the system derives turnover rate at the first limit-up time from cumulative volume divided by free-float shares

### Requirement: Turnover at end of day
For each stock included for date \(D\), the system SHALL output the end-of-day turnover rate.

#### Scenario: End-of-day turnover from daily bar
- **WHEN** daily bar turnover rate is available for date \(D\)
- **THEN** the system outputs that daily turnover rate as end-of-day turnover

### Requirement: Structured output with required fields
The system SHALL produce a structured output for date \(D\) that includes, at minimum, stock identifier and the computed metrics: consecutive limit-up days, first limit-up time, final seal time, turnover at first limit-up, and end-of-day turnover.

#### Scenario: Minimal output fields present
- **WHEN** the report is generated successfully for date \(D\)
- **THEN** each stock record contains all required fields and a generation timestamp

### Requirement: Partial results and error reporting
If required intraday data is missing for a stock on date \(D\), the system SHALL still emit a record for that stock with a status indicating partial computation and a reason describing which inputs were missing.

#### Scenario: Missing minute-level data
- **WHEN** the stock is limit-up by end-of-day daily data but minute-level data for date \(D\) is unavailable
- **THEN** the record is emitted with status `partial` and a missing-data reason, and time-based metrics are left empty

