# ADR 014: Fingerprint trust and subprocess analyzer execution

- Status: Accepted
- Date: 2026-09-01

## Decision

MediaSensei binds local plugin approval to an exact SHA-256 source fingerprint and runs analyzer calls in a bounded, shell-free child process. Plugin runtime reloads happen only through an explicit command or API mutation. SDK-owned records enforce finite values, web URL rules, unique candidates, and serialized-size limits before data crosses into core domain code.

## Consequences

A changed plugin cannot execute using an old approval. Analyzer crashes, hangs, oversized output, and accidental environment-secret access are isolated from the API and CLI process. Operators can reason about runtime generations and recovery. Trust approval still imports reviewed Python source; signed packages and native operating-system sandbox profiles remain packaging concerns.