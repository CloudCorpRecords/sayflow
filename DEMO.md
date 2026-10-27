# Sayflow — demo video script (target 4:00, limit 5:00)

Format: screen recording of a terminal + the sample folders, with narration.
Reset before recording: `python3 reset_samples.py`

---

**[0:00–0:30] The problem**
*Screen: a folder full of Python/YAML automation code, then a blank text file.*
Narration: "Agent automations are powerful — but they're written in languages only programmers can read. The people who actually know the workflow can't write them, can't check them, can't fix them. So I built a language you write the way you'd say it. This is Sayflow."

**[0:30–1:15] A first program, read aloud**
*Screen: `examples/file-triage.say` open in an editor. Highlight lines as read.*
Narration: "Here's a whole workflow. 'For each file in the inbox — if the filename contains invoice, move it to the invoices folder. Otherwise, if it's a markdown file, it goes to notes; a CSV goes to data; anything else goes to other.' No imports, no brackets, no semicolons. One idea per line. Blocks close with the word 'end'."

**[1:15–2:15] Run it — the trace is the interface**
*Screen: terminal. Run `python3 sayflow.py examples/file-triage.say`. Scroll with the trace; then show `sample/sorted/` folders filled.*
Narration: "When Sayflow runs, it narrates itself. Step five: five files found. Step six: this one contains 'invoice' — true. Step seven: moved. Every decision is printed, in order, in plain words. At the end — invoices, notes, data, other, all sorted for real. The trace means the author never has to trust the machine blindly; they can audit exactly what it did."

**[2:15–3:15] A second domain in seconds: reminder digest**
*Screen: `examples/reminder-digest.say`, then run it; open `sample/out/digest.txt`.*
Narration: "Same language, different job. This program reads a reminder list — date, task, flag — picks the fields apart with 'field 1 of line split by,' groups urgent first, then today, then later, and writes a digest file. Notice 'collect': collecting builds a list that quietly refuses duplicates. And 'length of' counts in words, not symbols."

**[3:15–4:00] Data cleanup + safety + friendly errors**
*Screen: run `examples/data-cleanup.say`; show before/after of the CSV. Then type a deliberate typo line (`frobnicate the inbox`) and run `--check`; then show a path-escape being refused (self-test output).*
Narration: "Third example: a messy CSV — ragged spaces, shouting capitals, duplicate people — cleaned into one tidy list by chaining little phrases: trimmed of, lowercase of, capitalised of. And two safety details: type a word Sayflow doesn't know and it answers with the line number and a hint, not a stack trace. Try to reach outside the workspace folder and it refuses, in plain English. A language for everyone has to be safe for everyone."

**[4:00–4:30] Close**
*Screen: the three example programs side by side; final line on screen: "If you can say it, you can automate it."*
Narration: "Sayflow is one Python file, zero dependencies, with a self-test that runs all three workflows and checks the real results — eight for eight. The full grammar fits on one page of the README. If you can say it, you can automate it. Thanks for watching."

---

Notes for recording:
- Re-run `python3 reset_samples.py` between takes (triage moves files).
- Keep terminal font large; the trace is the star.
- All commands shown actually work as filmed; no mock output anywhere.
