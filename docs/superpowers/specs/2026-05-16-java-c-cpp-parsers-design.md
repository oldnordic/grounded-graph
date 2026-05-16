# Sub-project #4 — Java + C + C++ parsers

**Status:** Approved.
**Date:** 2026-05-16.
**Scope:** grounded-index only. Version: 0.2.0 → 0.3.0.

## Goal

Extend grounded-index's tree-sitter coverage from Rust/TS/JS to Java, C, and C++. grounded-graph automatically benefits — the loader is language-agnostic.

## Phase 0 evidence

- `tree-sitter-java 0.23.5`, `tree-sitter-c 0.24.2`, `tree-sitter-cpp 0.23.4` all on PyPI.
- Java top-level: `package_declaration`, `import_declaration`, `class_declaration`, `interface_declaration`, `enum_declaration`, `annotation_type_declaration`.
- C top-level: `preproc_include`, `preproc_def`, `type_definition`, `function_definition`, `declaration`.
- C++ top-level: + `namespace_definition`, `class_specifier`, `template_declaration`.
- References: Java `method_invocation`/`object_creation_expression`, C/C++ `call_expression`.

## Symbol kinds

| Java                | C            | C++                                     |
|---------------------|--------------|-----------------------------------------|
| class, interface, enum, annotation | struct, union, enum | class, struct, union, enum, namespace |
| method, constructor, field         | function, macro, typedef | function, method, constructor, destructor, field, macro, typedef |

## Imports

- Java: `import_declaration` → `Import(module=<scoped>, imported=<last_id>)`; static imports keep the qualifier in `module`.
- C/C++: `preproc_include` → `Import(module=<header>, imported=None, is_relative=is_string_literal)`.

## References

- Java: `method_invocation` → `call`; `object_creation_expression` → `constructor`.
- C: `call_expression` → `call`.
- C++: `call_expression` → `call`; through `scoped_identifier` for `foo::bar`.

## Visibility

- Java: explicit `public` modifier.
- C: not `static` at file scope.
- C++: last seen access specifier above the member; free functions True unless `static`.

## Test detection (path-based only)

- Java: file path contains `src/test/` or `test/`.
- C/C++: file path contains `tests/`, `test/`, or basename ends `_test.{c,cpp,cc,cxx,c++}`.
- Method-level Java: `@Test`/`@ParameterizedTest`/`@RepeatedTest` annotation in `modifiers`.

JUnit/Catch2/GTest macro/callback extraction: out of scope.

## Language detection

| extension | language |
|---|---|
| `.java` | Java |
| `.c`, `.h` | C |
| `.cpp`, `.cc`, `.cxx`, `.c++`, `.hpp`, `.hh`, `.hxx`, `.h++` | C++ |

`.h` defaults to C (industry convention); users with pure-C++ headers should rename.

## Versioning

- `grounded-index` 0.2.0 → **0.3.0**. SemVer minor.
- No grounded-graph bump (loader is language-agnostic).
