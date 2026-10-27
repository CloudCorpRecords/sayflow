# Sayflow — Devpost submission copy (Syntax Summit)

**Project name:** Sayflow

**Tagline:** Write agent workflows the way you'd say them.

**Elevator pitch (short description):**
Sayflow is a plain-English programming language for agent workflows. Non-programmers write automations as near-English lines; Sayflow compiles them into an executable workflow and runs it with a visible step trace, so anyone can follow, trust, and audit exactly what the automation did.

---

## Inspiration

Every agent workflow today is locked inside Python, YAML, or a drag-and-drop builder — yet the people who best understand the workflow (the office manager, the nurse, the shop owner) can't write or even read any of those. We asked: what if the program *was* the description? If you can say "for each file in the inbox, if its name contains invoice, move it to the invoices folder," you should be able to run exactly that sentence.

## What it does

Sayflow is a complete little language: a lexer, a recursive-descent parser, and a tree-walking interpreter in a single dependency-free Python file.

You write lines like:

```
for each file in "sample/inbox":
  if filename contains "invoice":
    move file to "sample/sorted/invoices"
  end
end
```

and Sayflow executes them — with a numbered step trace showing every value set, every condition checked, and every file moved. It ships with three real example workflows that run end-to-end: a file triage that sorts a messy inbox, a reminder digest builder, and a CSV data-cleanup that trims, normalises, and deduplicates rows. Programs are sandboxed to their workspace folder, and mistakes produce friendly errors ("Line 4: I don't know the word 'frobnicate'…") instead of stack traces.

The language covers: named values, file read/write/append/move/copy/delete, folder loops and line loops, nested if/otherwise choices with word-based conditions (contains, equals, starts with, is more than, is empty…), chaining text transforms (lowercase of, trimmed of, capitalised of, length of), CSV-style field picking (field 2 of line split by ","), and de-duplicating collections.

## How I built it

A single Python 3 file, standard library only. The lexer tokenises each line (quote-aware comment stripping); the parser builds nested statement blocks recursively; the interpreter executes with an environment of named values and prints the trace as it runs. Getting transform binding right was the interesting bug: "capitalised of name + …" initially title-cased the whole sentence, which the built-in self-test caught — transforms now bind tightly to the one value after "of," the way English reads. `--selftest` runs all three examples in a throwaway sandbox and asserts the real outcomes (files sorted, digest grouped, duplicates gone): 8/8 checks passing.

## Challenges I ran into

- Making an English-like grammar unambiguous without making it feel like code in disguise — solved with tight transform binding and a small, closed set of statement starters.
- Loops that move the very files being listed — solved by snapshotting the folder listing before iterating.
- Keeping the trace readable while loops repeat steps — the trace shows every iteration honestly, because the audit trail is the point.

## Accomplishments that I'm proud of

- A non-programmer can read any of the three example programs aloud and correctly predict what will happen — then watch the trace prove it.
- Real file operations, real deduplication semantics, real sandboxing — no mocks anywhere in the demo path.
- Zero dependencies: clone it and it runs.

## What I learned

Language design is user-experience design. Every grammar choice is a bet about what a sentence means to a reader, and the self-test's job was to catch the places where my bet and English disagreed.

## What's next for Sayflow

- An `ask` statement — a human approval gate written in English.
- Read-aloud traces for accessibility, and `send`/`fetch` steps for email and web sources behind the same visible trace.

## Built with

- Python 3 (standard library only — custom lexer, parser, and interpreter)
- Plain-text sample data, generated deterministically by `reset_samples.py`

## Try it out

- Repo: https://github.com/CloudCorpRecords/sayflow
- Run: `python3 sayflow.py examples/reminder-digest.say`
- Test: `python3 sayflow.py --selftest`
- Screenshot and full language reference: see the repository README.

## Build Disclosure

Build Disclosure: AI-built. Built by AI agents (Tree / Muse fleet) directed by Rene Turcios during the hackathon period; Rene set the direction and reviewed; agents designed, coded, and tested.
