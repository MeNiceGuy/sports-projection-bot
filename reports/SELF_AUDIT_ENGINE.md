# Self-Audit Engine

## Goal
Let the sports bot review its own logs and reporting outputs, generate upgrade suggestions, and wait for human approval before any major change is applied.

## What it does now
- reads grading summary
- reads confidence-bucket report
- proposes structured upgrade suggestions
- writes approval-ready suggestions to `reports/upgrade_suggestions.json`

## What it does not do
- change code automatically
- adjust live logic automatically
- self-modify without approval

This keeps the system ambitious without making it reckless.
