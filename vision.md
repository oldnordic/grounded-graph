# grounded-graph Vision

Large repositories are too expensive to navigate with full file reads. AI assistants need compact, verifiable context: where a symbol is defined, who calls it, what tests cover it, what contracts it touches, and which files are likely relevant.

`grounded-graph` should provide that context as an embedded graph.

## Product Shape

The tool should feel like a code intelligence layer, not an AI agent. It indexes source code and exposes graph queries that agents and developers can use.

Core promise:

```text
Give the assistant the smallest evidence pack that can support the next decision.
```

## Graph Model

Candidate node types:

- `file`
- `module`
- `package`
- `class`
- `interface`
- `function`
- `method`
- `test`
- `config`
- `route`
- `database_object`

Candidate edge types:

- `defines`
- `imports`
- `calls`
- `references`
- `implements`
- `extends`
- `tests`
- `configures`
- `depends_on`
- `writes`
- `reads`
- `emits`

## Compliance Positioning

This should be easy to explain to a bank security team:

- It is an offline metadata index over project files.
- It does not send source code anywhere.
- It does not require a server.
- It does not modify source files.
- It writes only its project-scoped metadata database.
- It can report exactly which files it read and what metadata it stored.

## Success Criteria

- Reduce broad file reads for AI coding tasks.
- Produce repeatable context packs.
- Make impact analysis faster.
- Make handoffs between agents more precise.
- Keep output small enough for controlled prompting.

