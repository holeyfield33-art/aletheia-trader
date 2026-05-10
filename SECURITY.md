# Security Policy

## Supported Versions

This repository currently supports the latest `main` branch for security updates.

## Reporting a Vulnerability

Please report vulnerabilities privately and do not open a public issue for active security concerns.

- Email: security@aletheia-core.com
- Include: affected component, reproduction steps, expected impact, and any suggested remediation.

We will acknowledge reports within 3 business days and provide regular status updates while triaging.

## Security Practices in This Repo

- Human-in-the-loop paper trading only by default.
- Optional API key protection for API access.
- Audit receipts attached to signal generation and decisions.
- Input validation for prices, quantities, symbols, and order state transitions.
- Market Watcher decisions and published signals route through `core/aletheia_guard.py`.
- WebSocket market watcher stream endpoint exists at `/v1/market-watcher/stream`; deploy behind trusted network boundaries if API auth is disabled.
- Sentiment providers are failover-aware with cooldown to reduce repeated dependency failures.
