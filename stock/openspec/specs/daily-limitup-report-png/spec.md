# 每日涨停报告 PNG（daily-limitup-report-png）

本文档由变更 `daily-limitup-report-png` 合并入主规格库。

## Requirements

### Requirement: Generate PNG from daily limit-up report JSON
The system SHALL generate one or more PNG image files from a given trading date’s daily limit-up report JSON output.

#### Scenario: Generate PNG for a specified date
- **WHEN** the operator runs the PNG generator with trading date \(D\)
- **THEN** the system reads the corresponding `daily_limitup_report` JSON for \(D\) and produces PNG file(s) for \(D\)

### Requirement: PNG includes required fields and headers
Each generated PNG SHALL include the trading date \(D\), a generation timestamp, and a tabular listing of stocks with key fields: stock identifier, stock name, consecutive limit-up days, first limit-up time, final seal time, turnover at first limit-up, and end-of-day turnover.

#### Scenario: Required fields appear on the image
- **WHEN** the PNG is generated successfully
- **THEN** the image contains a header section and the required columns for each stock row

### Requirement: Paginate output when rows exceed page capacity
If the number of stock rows exceeds the configured per-page capacity, the system SHALL split output into multiple PNG pages with stable, predictable file names.

#### Scenario: Multi-page output
- **WHEN** the input report contains more rows than the configured page size
- **THEN** the system generates `page_1.png`, `page_2.png`, ... until all rows are rendered

### Requirement: Deterministic output path and overwrite on rerun
The system SHALL write PNG outputs to a deterministic directory path based on trading date \(D\), and SHALL overwrite existing PNG outputs for \(D\) on rerun.

#### Scenario: Rerun overwrites files
- **WHEN** the generator is run again for the same date \(D\)
- **THEN** previously generated PNG outputs for \(D\) are replaced with the newly generated files

### Requirement: Handle partial rows gracefully
If some fields are missing in the input JSON (e.g., due to `status=partial`), the system SHALL still render the row and display placeholders for missing values.

#### Scenario: Missing fields display placeholders
- **WHEN** a stock row has missing time or turnover fields
- **THEN** the image displays `--` (or an equivalent placeholder) for those fields without failing the whole generation
