# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [0.1.0] — 2026-11-23

### Added
- Unified `MobileMoney` client with automatic operator detection from the phone prefix.
- **MVola** Merchant Pay: token, payment, status, transaction details, callbacks.
- **Orange Money** Web Payment: payment page, status, notifications with `notif_token` check.
- **Airtel Money** Collection: USSD push, status (`TS`/`TF`/`TIP`/`TA`), callbacks.
- Offline **simulator** with deterministic outcomes, plus `python -m mobile_money_mg` demo.
- `wait()` polling helper with back-off, `confirm_webhook()` that re-checks with the operator.
- Malagasy phone number normalisation (`034 12 345 67`, `+261…`, `261…`).
- Configuration from environment variables (`MobileMoney.from_env()`).
- FastAPI and Django examples, full type hints, 95%+ test coverage.
