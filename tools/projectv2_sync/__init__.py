"""
ProjectV2 sync (dry-run).

This package extracts actionable "Task" items and referenced "Doc" items from
local markdown checklists under docs/operations/, and emits a normalized JSON
payload that can later be written into GitHub Projects V2 via GraphQL.

Dry-run only: no network calls are made by default.
"""

