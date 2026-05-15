# grounded-graph

`grounded-graph` is a planned embedded code metadata graph for helping AI coding agents navigate repositories through evidence instead of broad file reads.

## Goal

Build a project-scoped graph database that captures symbols, files, modules, calls, references, tests, and dependency relationships. The first version should be deterministic, offline, read-only by default, and suitable for restricted corporate environments.

## First Principles

- Repository evidence is the source of truth.
- No network access by default.
- No model calls in the core graph engine.
- Store metadata in an embedded database.
- Return token-bounded Markdown or JSON context for AI assistants.
- Prefer explicit graph edges over inferred explanations.

## Initial Scope

- Index project files into graph nodes and edges.
- Store metadata in SQLite.
- Query symbol neighborhoods with depth and token limits.
- Find callers, references, related tests, and impact paths.
- Export compact context blocks for Copilot, Claude, ChatGPT, or Codex.

## Out Of Scope Initially

- Automated code mutation.
- Refactoring edits.
- LLM-powered ranking.
- Network services.
- IDE plugin work.

## Candidate Commands

```bash
grounded-graph index .
grounded-graph status
grounded-graph find-symbol CustomerService
grounded-graph context CustomerService --budget 4000
grounded-graph callers CustomerService.updateCustomer
grounded-graph tests-for CustomerService
grounded-graph impact src/main/java/example/CustomerService.java
grounded-graph neighborhood CustomerService --depth 2 --budget 6000
```

