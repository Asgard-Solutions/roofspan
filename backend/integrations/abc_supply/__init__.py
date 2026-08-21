"""ABC Supply integration package (RoofSpan Office / Desktop only).

Centralizes all ABC Supply API access behind a provider abstraction: configuration,
OAuth 2.0 (authorization code + PKCE and client credentials), a common async HTTP
client (retries / 429 / timeouts / error normalization), and per-API modules
(accounts, locations, products, pricing, orders, notifications).

This package contains NO business-data persistence. Token storage and RoofSpan
purchasing linkage live in the local FastAPI router/models against local PostgreSQL.
"""
