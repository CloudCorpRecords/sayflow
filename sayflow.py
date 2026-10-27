#!/usr/bin/env python3
"""
Sayflow — a plain-English language for agent workflows.

Write automations the way you would say them out loud:

    workflow "File Triage"
    for each file in "sample/inbox":
      if filename contains "invoice":
        move file to "sample/sorted/invoices"
      end
    end
    say "Done"

Sayflow parses each near-English line, compiles it to an executable
workflow, and runs it with a visible step trace so you can watch every
decision the workflow makes.

Standard library only. Python 3.9+.

Usage:
    python3 sayflow.py <program.say> [--root DIR] [--quiet]
    python3 sayflow.py --check <program.say>     parse only, no run
    python3 sayflow.py --selftest                run the built-in tests
"""

import os
import re
import shutil
import sys
import tempfile

VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class SayflowError(Exception):
    """An error with a source line attached, written for humans."""

    def __init__(self, message, lineno=None, source=None):
        self.lineno = lineno
        self.source = source
        super().__init__(message)

    def render(self):
        if self.lineno is not None:
            return "Line {}: {}\n    {}".format(self.lineno, self, self.source or "")
        return str(self)


# ---------------------------------------------------------------------------
# Tokeniser
# ---------------------------------------------------------------------------

TOKEN_RE = re.compile(
    r'''
    (?P<string>"(?:[^"\\]|\\.)*")
  | (?P<number>\d+(?:\.\d+)?)
  | (?P<name>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<symbol>[+(),:])
  | (?P<space>\s+)
  | (?P<other>.)
    ''',
    re.VERBOSE,
)


class Token:
    def __init__(self, kind, text):
        self.kind = kind
        self.text = text

    def __repr__(self):
        return "Token({!r}, {!r})".format(self.kind, self.text)


def unquote(text):
    body = text[1:-1]
    out = []
    i = 0
    while i < len(body):
        ch = body[i]
        if ch == "\\" and i + 1 < len(body):
            nxt = body[i + 1]
            out.append({"n": "\n", "t": "\t", '"': '"', "\\": "\\"}.get(nxt, nxt))
            i += 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def tokenise(text, lineno, source):
    tokens = []
    for match in TOKEN_RE.finditer(text):
        kind = match.lastgroup
        if kind == "space":
            continue
        if kind == "other":
            raise SayflowError(
                "I don't understand the character {!r} here.".format(match.group()),
                lineno, source)
        tokens.append(Token(kind, match.group()))
    return tokens


def strip_comment(line):
    """Remove a trailing # comment, unless the # is inside a string."""
    in_string = False
    i = 0
    while i < len(line):
        ch = line[i]
        if ch == "\\" and in_string:
            i += 2
            continue
        if ch == '"':
            in_string = not in_string
        elif ch == "#" and not in_string:
            return line[:i]
        i += 1
    return line


# ---------------------------------------------------------------------------
# AST nodes (plain tuples keep this simple: (kind, lineno, source, ...))
# ---------------------------------------------------------------------------
# Statements:
#   ("workflow", name_expr)
#   ("say", expr)
#   ("set", var, expr)
#   ("read", path_expr, var)
#   ("foreach_file", path_expr, body)
#   ("foreach_line", src_expr, body)
#   ("if", cond, then_body, else_body)
#   ("move", src_expr, dst_expr) / ("copy", ...) / ("delete", expr)
#   ("makefolder", expr)
#   ("write", value_expr, path_expr) / ("append", value_expr, path_expr)
#   ("collect", expr, var)
#   ("countfiles", path_expr, var)
#   ("stop",)
# Expressions:
#   ("lit", value) ("var", name) ("concat", a, b)
#   ("transform", op, expr)   op in lowercase/uppercase/capitalised/trimmed/length
#   ("field", n, expr, sep)
# Conditions:
#   ("contains", a, b) ("equals", a, b) ("startswith", a, b) ("endswith", a, b)
#   ("morethan", a, b) ("lessthan", a, b) ("atleast", a, b)
#   ("empty", a) ("notempty", a)


TRANSFORMS = ("lowercase", "uppercase", "capitalised", "trimmed", "length")


class ExprParser:
    """Recursive-descent parser for one expression's token list."""

    def __init__(self, tokens, lineno, source):
        self.tokens = tokens
        self.pos = 0
        self.lineno = lineno
        self.source = source

    # -- token helpers ------------------------------------------------------
    def peek(self, offset=0):
        idx = self.pos + offset
        if idx < len(self.tokens):
            return self.tokens[idx]
        return None

    def peek_word(self, offset=0):
        tok = self.peek(offset)
        if tok is not None and tok.kind == "name":
            return tok.text.lower()
        return None

    def next(self):
        tok = self.peek()
        self.pos += 1
        return tok

    def at_end(self):
        return self.pos >= len(self.tokens)

    def expect_word(self, word):
        if self.peek_word() != word:
            raise SayflowError(
                "I expected the word {!r} here.".format(word), self.lineno, self.source)
        self.pos += 1

    def expect_end(self, what="expression"):
        if not self.at_end():
            raise SayflowError(
                "I got lost near {!r} in this {}.".format(self.peek().text, what),
                self.lineno, self.source)

    # -- grammar ------------------------------------------------------------
    # parse_expr  : additive level —  unary (('+' | 'plus') unary)*
    # parse_unary : a transform ('lowercase of ...'), a field pick
    #               ('field 2 of line split by ","'), or a single term.
    #               Transforms bind tightly to the one value after 'of',
    #               so  capitalised of name + "!"  titles the name, not
    #               the whole sentence.
    def parse_expr(self):
        left = self.parse_unary()
        while True:
            tok = self.peek()
            if tok is not None and tok.kind == "symbol" and tok.text == "+":
                self.next()
                left = ("concat", left, self.parse_unary())
            elif self.peek_word() == "plus":
                self.next()
                left = ("concat", left, self.parse_unary())
            else:
                return left

    def parse_unary(self):
        word = self.peek_word()
        if word in TRANSFORMS:
            self.next()
            self.expect_word("of")
            operand = self.parse_unary()
            return ("transform", word, operand)
        if word == "field":
            self.next()
            num = self.next()
            if num is None or num.kind != "number":
                raise SayflowError(
                    "'field' needs a number, as in: field 2 of line split by \",\"",
                    self.lineno, self.source)
            self.expect_word("of")
            operand = self.parse_unary()
            self.expect_word("split")
            self.expect_word("by")
            sep = self.next()
            if sep is None or sep.kind != "string":
                raise SayflowError(
                    "'split by' needs a quoted separator, as in: split by \",\"",
                    self.lineno, self.source)
            return ("field", int(float(num.text)), operand, unquote(sep.text))
        return self.parse_term()

    def parse_term(self):
        tok = self.next()
        if tok is None:
            raise SayflowError("This line seems to end too early.",
                               self.lineno, self.source)
        if tok.kind == "string":
            return ("lit", unquote(tok.text))
        if tok.kind == "number":
            value = float(tok.text)
            return ("lit", int(value) if value.is_integer() else value)
        if tok.kind == "symbol" and tok.text == "(":
            inner = self.parse_expr()
            closing = self.next()
            if closing is None or closing.text != ")":
                raise SayflowError("I expected a closing ')' here.",
                                   self.lineno, self.source)
            return inner
        if tok.kind == "name":
            return ("var", tok.text.lower())
        raise SayflowError(
            "I don't understand {!r} here.".format(tok.text), self.lineno, self.source)

    def parse_condition(self):
        left = self.parse_expr()
        word = self.peek_word()
        if word == "contains":
            self.next()
            return ("contains", left, self.parse_expr())
        if word == "equals":
            self.next()
            return ("equals", left, self.parse_expr())
        if word == "starts":
            self.next()
            self.expect_word("with")
            return ("startswith", left, self.parse_expr())
        if word == "ends":
            self.next()
            self.expect_word("with")
            return ("endswith", left, self.parse_expr())
        if word == "is":
            self.next()
            nxt = self.peek_word()
            if nxt == "empty":
                self.next()
                return ("empty", left)
            if nxt == "not":
                self.next()
                self.expect_word("empty")
                return ("notempty", left)
            if nxt == "more":
                self.next()
                self.expect_word("than")
                return ("morethan", left, self.parse_expr())
            if nxt == "less":
                self.next()
                self.expect_word("than")
                return ("lessthan", left, self.parse_expr())
            if nxt == "at":
                self.next()
                self.expect_word("least")
                return ("atleast", left, self.parse_expr())
            return ("equals", left, self.parse_expr())
        raise SayflowError(
            "I need a comparison here — try 'contains', 'equals', 'starts with', "
            "'is more than', or 'is empty'.", self.lineno, self.source)


# ---------------------------------------------------------------------------
# Statement parser: turns source lines into a nested statement list.
# Blocks open with a trailing ':' and close with the word 'end'.
# 'otherwise:' opens the else-branch of the nearest 'if'.
# ---------------------------------------------------------------------------


class ProgramParser:
    def __init__(self, text):
        self.lines = []  # (lineno, stripped_text)
        for lineno, raw in enumerate(text.splitlines(), start=1):
            stripped = strip_comment(raw).strip()
            if stripped:
                self.lines.append((lineno, stripped))
        self.pos = 0

    def parse(self):
        body, _ = self.parse_block(stop_words=())
        return body

    def current(self):
        if self.pos < len(self.lines):
            return self.lines[self.pos]
        return (None, None)

    def parse_block(self, stop_words):
        """Parse statements until a line whose first word is in stop_words.
        Returns (statements, stop_word_or_None). Does not consume the stop line."""
        statements = []
        while self.pos < len(self.lines):
            lineno, text = self.lines[self.pos]
            first = text.split(None, 1)[0].lower().rstrip(":")
            if first in stop_words:
                return statements, first
            statements.append(self.parse_statement())
        return statements, None

    def parse_statement(self):
        lineno, text = self.lines[self.pos]
        opens_block = text.endswith(":")
        body_text = text[:-1].strip() if opens_block else text
        tokens = tokenise(body_text, lineno, text)
        if not tokens or tokens[0].kind != "name":
            raise SayflowError("I don't understand this line.", lineno, text)
        head = tokens[0].text.lower()
        ep = ExprParser(tokens[1:], lineno, text)

        def need_block(keyword):
            if not opens_block:
                raise SayflowError(
                    "A '{}' line must end with ':' so I know a block follows.".format(keyword),
                    lineno, text)

        if head == "workflow":
            expr = ep.parse_expr()
            ep.expect_end()
            self.pos += 1
            return ("workflow", lineno, text, expr)

        if head == "say":
            expr = ep.parse_expr()
            ep.expect_end()
            self.pos += 1
            return ("say", lineno, text, expr)

        if head == "set":
            var_tok = ep.next()
            if var_tok is None or var_tok.kind != "name":
                raise SayflowError("'set' needs a name, as in: set total to 0",
                                   lineno, text)
            ep.expect_word("to")
            expr = ep.parse_expr()
            ep.expect_end()
            self.pos += 1
            return ("set", lineno, text, var_tok.text.lower(), expr)

        if head == "read":
            expr = ep.parse_expr()
            ep.expect_word("into")
            var_tok = ep.next()
            if var_tok is None or var_tok.kind != "name":
                raise SayflowError("'read ... into' needs a name at the end.",
                                   lineno, text)
            ep.expect_end()
            self.pos += 1
            return ("read", lineno, text, expr, var_tok.text.lower())

        if head == "for":
            ep.expect_word("each")
            kind_tok = ep.next()
            if kind_tok is None or kind_tok.text.lower() not in ("file", "line"):
                raise SayflowError(
                    "After 'for each' I expect 'file' or 'line'.", lineno, text)
            ep.expect_word("in")
            expr = ep.parse_expr()
            ep.expect_end()
            need_block("for")
            self.pos += 1
            body, stop = self.parse_block(stop_words=("end",))
            if stop != "end":
                raise SayflowError(
                    "This 'for each' block never closes — add an 'end' line.",
                    lineno, text)
            self.pos += 1  # consume 'end'
            kind = "foreach_file" if kind_tok.text.lower() == "file" else "foreach_line"
            return (kind, lineno, text, expr, body)

        if head == "if":
            cond = ep.parse_condition()
            ep.expect_end("condition")
            need_block("if")
            self.pos += 1
            then_body, stop = self.parse_block(stop_words=("otherwise", "end"))
            else_body = []
            if stop == "otherwise":
                self.pos += 1  # consume 'otherwise:'
                else_body, stop = self.parse_block(stop_words=("end",))
            if stop != "end":
                raise SayflowError(
                    "This 'if' block never closes — add an 'end' line.", lineno, text)
            self.pos += 1  # consume 'end'
            return ("if", lineno, text, cond, then_body, else_body)

        if head in ("move", "copy"):
            src = ep.parse_expr()
            ep.expect_word("to")
            dst = ep.parse_expr()
            ep.expect_end()
            self.pos += 1
            return (head, lineno, text, src, dst)

        if head == "delete":
            expr = ep.parse_expr()
            ep.expect_end()
            self.pos += 1
            return ("delete", lineno, text, expr)

        if head == "make":
            ep.expect_word("folder")
            expr = ep.parse_expr()
            ep.expect_end()
            self.pos += 1
            return ("makefolder", lineno, text, expr)

        if head in ("write", "append"):
            value = ep.parse_expr()
            ep.expect_word("to")
            path = ep.parse_expr()
            ep.expect_end()
            self.pos += 1
            return (head, lineno, text, value, path)

        if head == "collect":
            expr = ep.parse_expr()
            ep.expect_word("in")
            var_tok = ep.next()
            if var_tok is None or var_tok.kind != "name":
                raise SayflowError("'collect ... in' needs a name at the end.",
                                   lineno, text)
            ep.expect_end()
            self.pos += 1
            return ("collect", lineno, text, expr, var_tok.text.lower())

        if head == "count":
            ep.expect_word("files")
            ep.expect_word("in")
            expr = ep.parse_expr()
            ep.expect_word("into")
            var_tok = ep.next()
            if var_tok is None or var_tok.kind != "name":
                raise SayflowError("'count files in ... into' needs a name at the end.",
                                   lineno, text)
            ep.expect_end()
            self.pos += 1
            return ("countfiles", lineno, text, expr, var_tok.text.lower())

        if head == "stop":
            ep.expect_end()
            self.pos += 1
            return ("stop", lineno, text)

        raise SayflowError(
            "I don't know the word {!r} at the start of a line. Lines can start "
            "with: workflow, say, set, read, for each, if, move, copy, delete, "
            "make folder, write, append, collect, count files, stop.".format(head),
            lineno, text)


# ---------------------------------------------------------------------------
# Interpreter
# ---------------------------------------------------------------------------


class StopWorkflow(Exception):
    pass


def stringify(value):
    if isinstance(value, list):
        return "\n".join(str(item) for item in value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def interpolate(text, env):
    def repl(match):
        name = match.group(1).strip().lower()
        if name in env:
            return stringify(env[name])
        return match.group(0)

    return re.sub(r"\{([A-Za-z_][A-Za-z0-9_ ]*)\}", repl, text)


class Runner:
    def __init__(self, root, quiet=False):
        self.root = os.path.abspath(root)
        self.quiet = quiet
        self.env = {}
        self.step = 0

    # -- output -------------------------------------------------------------
    def trace(self, lineno, source, detail=""):
        self.step += 1
        if not self.quiet:
            line = "[{:>2}] {}".format(self.step, source)
            if detail:
                line += "   -> {}".format(detail)
            print(line)

    def out(self, text):
        print("     " + text.replace("\n", "\n     "))

    # -- paths (sandboxed to root) ------------------------------------------
    def resolve(self, path, lineno, source):
        full = os.path.abspath(os.path.join(self.root, str(path)))
        if full != self.root and not full.startswith(self.root + os.sep):
            raise SayflowError(
                "That path leaves the workspace ({}) — Sayflow only works "
                "inside its root folder.".format(path), lineno, source)
        return full

    def rel(self, full):
        return os.path.relpath(full, self.root)

    # -- expressions ----------------------------------------------------------
    def eval_expr(self, node, lineno, source):
        kind = node[0]
        if kind == "lit":
            value = node[1]
            if isinstance(value, str):
                return interpolate(value, self.env)
            return value
        if kind == "var":
            name = node[1]
            if name not in self.env:
                raise SayflowError(
                    "I don't know a value called {!r} yet — 'set' it first.".format(name),
                    lineno, source)
            return self.env[name]
        if kind == "concat":
            left = self.eval_expr(node[1], lineno, source)
            right = self.eval_expr(node[2], lineno, source)
            if isinstance(left, (int, float)) and isinstance(right, (int, float)):
                return left + right
            return stringify(left) + stringify(right)
        if kind == "transform":
            op, operand = node[1], self.eval_expr(node[2], lineno, source)
            if op == "length":
                if isinstance(operand, (list, str)):
                    return len(operand)
                return len(stringify(operand))
            text = stringify(operand)
            if op == "lowercase":
                return text.lower()
            if op == "uppercase":
                return text.upper()
            if op == "capitalised":
                return text.title()
            if op == "trimmed":
                return text.strip()
        if kind == "field":
            _, n, operand_node, sep = node
            operand = stringify(self.eval_expr(operand_node, lineno, source))
            parts = operand.split(sep)
            if 1 <= n <= len(parts):
                return parts[n - 1]
            return ""
        raise SayflowError("Internal error: unknown expression {!r}.".format(kind),
                           lineno, source)

    def eval_cond(self, node, lineno, source):
        kind = node[0]
        if kind == "empty":
            value = self.eval_expr(node[1], lineno, source)
            return stringify(value).strip() == ""
        if kind == "notempty":
            value = self.eval_expr(node[1], lineno, source)
            return stringify(value).strip() != ""
        left = self.eval_expr(node[1], lineno, source)
        right = self.eval_expr(node[2], lineno, source)
        if kind == "contains":
            return stringify(right) in stringify(left)
        if kind == "equals":
            if isinstance(left, (int, float)) and isinstance(right, (int, float)):
                return left == right
            return stringify(left) == stringify(right)
        if kind == "startswith":
            return stringify(left).startswith(stringify(right))
        if kind == "endswith":
            return stringify(left).endswith(stringify(right))
        if kind in ("morethan", "lessthan", "atleast"):
            try:
                lnum, rnum = float(left), float(right)
            except (TypeError, ValueError):
                raise SayflowError(
                    "That comparison needs numbers on both sides.", lineno, source)
            if kind == "morethan":
                return lnum > rnum
            if kind == "lessthan":
                return lnum < rnum
            return lnum >= rnum
        raise SayflowError("Internal error: unknown condition {!r}.".format(kind),
                           lineno, source)

    # -- statements -----------------------------------------------------------
    def run(self, statements):
        try:
            self.exec_block(statements)
        except StopWorkflow:
            pass
        if not self.quiet:
            print("-- done in {} step{} --".format(
                self.step, "" if self.step == 1 else "s"))

    def exec_block(self, statements):
        for stmt in statements:
            self.exec_stmt(stmt)

    def exec_stmt(self, stmt):
        kind, lineno, source = stmt[0], stmt[1], stmt[2]

        if kind == "workflow":
            name = stringify(self.eval_expr(stmt[3], lineno, source))
            self.step += 1
            if not self.quiet:
                print('== workflow "{}" =='.format(name))
            return

        if kind == "say":
            value = stringify(self.eval_expr(stmt[3], lineno, source))
            self.trace(lineno, source)
            self.out(value)
            return

        if kind == "set":
            value = self.eval_expr(stmt[4], lineno, source)
            self.env[stmt[3]] = value
            self.trace(lineno, source, "{} = {!r}".format(
                stmt[3], value if not isinstance(value, list) else "[{} items]".format(len(value))))
            return

        if kind == "read":
            path = stringify(self.eval_expr(stmt[3], lineno, source))
            full = self.resolve(path, lineno, source)
            if not os.path.isfile(full):
                raise SayflowError("There is no file at {}.".format(path), lineno, source)
            with open(full, "r", encoding="utf-8") as fh:
                self.env[stmt[4]] = fh.read()
            self.trace(lineno, source, "read {}".format(path))
            return

        if kind == "foreach_file":
            folder = stringify(self.eval_expr(stmt[3], lineno, source))
            full = self.resolve(folder, lineno, source)
            if not os.path.isdir(full):
                raise SayflowError("There is no folder at {}.".format(folder), lineno, source)
            names = sorted(n for n in os.listdir(full)
                           if os.path.isfile(os.path.join(full, n)))
            self.trace(lineno, source, "{} file{}".format(
                len(names), "" if len(names) == 1 else "s"))
            saved = {k: self.env.get(k) for k in ("file", "filename", "extension")}
            for name in names:
                self.env["file"] = os.path.join(folder, name)
                self.env["filename"] = name
                self.env["extension"] = os.path.splitext(name)[1].lstrip(".").lower()
                self.exec_block(stmt[4])
            for key, val in saved.items():
                if val is None:
                    self.env.pop(key, None)
                else:
                    self.env[key] = val
            return

        if kind == "foreach_line":
            src_value = self.eval_expr(stmt[3], lineno, source)
            if isinstance(src_value, list):
                items = [stringify(v) for v in src_value]
                origin = "a list"
            else:
                text = stringify(src_value)
                full = self.resolve(text, lineno, source) if text else None
                if full and os.path.isfile(full):
                    with open(full, "r", encoding="utf-8") as fh:
                        items = fh.read().splitlines()
                    origin = text
                else:
                    items = text.splitlines()
                    origin = "text"
            self.trace(lineno, source, "{} lines from {}".format(len(items), origin))
            saved = {k: self.env.get(k) for k in ("line", "linenumber")}
            for idx, item in enumerate(items, start=1):
                self.env["line"] = item
                self.env["linenumber"] = idx
                self.exec_block(stmt[4])
            for key, val in saved.items():
                if val is None:
                    self.env.pop(key, None)
                else:
                    self.env[key] = val
            return

        if kind == "if":
            result = self.eval_cond(stmt[3], lineno, source)
            self.trace(lineno, source, "true" if result else "false")
            self.exec_block(stmt[4] if result else stmt[5])
            return

        if kind in ("move", "copy"):
            src = stringify(self.eval_expr(stmt[3], lineno, source))
            dst = stringify(self.eval_expr(stmt[4], lineno, source))
            src_full = self.resolve(src, lineno, source)
            dst_full = self.resolve(dst, lineno, source)
            if not os.path.exists(src_full):
                raise SayflowError("There is nothing at {}.".format(src), lineno, source)
            # In Sayflow you move/copy a file *to a folder* (created if
            # needed); the file keeps its name. That is the plain-English
            # reading of "move file to sample/sorted/invoices".
            os.makedirs(dst_full, exist_ok=True)
            dst_full = os.path.join(dst_full, os.path.basename(src_full))
            if kind == "move":
                shutil.move(src_full, dst_full)
            else:
                shutil.copy2(src_full, dst_full)
            self.trace(lineno, source, "{} -> {}".format(src, self.rel(dst_full)))
            return

        if kind == "delete":
            path = stringify(self.eval_expr(stmt[3], lineno, source))
            full = self.resolve(path, lineno, source)
            if os.path.isfile(full):
                os.remove(full)
            self.trace(lineno, source, "deleted {}".format(path))
            return

        if kind == "makefolder":
            path = stringify(self.eval_expr(stmt[3], lineno, source))
            os.makedirs(self.resolve(path, lineno, source), exist_ok=True)
            self.trace(lineno, source, "folder {} ready".format(path))
            return

        if kind in ("write", "append"):
            value = self.eval_expr(stmt[3], lineno, source)
            path = stringify(self.eval_expr(stmt[4], lineno, source))
            full = self.resolve(path, lineno, source)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            text = stringify(value)
            mode = "w" if kind == "write" else "a"
            with open(full, mode, encoding="utf-8") as fh:
                fh.write(text)
                if text and not text.endswith("\n"):
                    fh.write("\n")
            self.trace(lineno, source, "{} {}".format(
                "wrote" if kind == "write" else "appended to", path))
            return

        if kind == "collect":
            value = self.eval_expr(stmt[3], lineno, source)
            bucket = self.env.setdefault(stmt[4], [])
            if not isinstance(bucket, list):
                raise SayflowError(
                    "{!r} already holds a single value, so I can't collect into it.".format(stmt[4]),
                    lineno, source)
            added = value not in bucket
            if added:
                bucket.append(value)
            self.trace(lineno, source, "{} now holds {} item{} ({})".format(
                stmt[4], len(bucket), "" if len(bucket) == 1 else "s",
                "added" if added else "duplicate skipped"))
            return

        if kind == "countfiles":
            folder = stringify(self.eval_expr(stmt[3], lineno, source))
            full = self.resolve(folder, lineno, source)
            if not os.path.isdir(full):
                raise SayflowError("There is no folder at {}.".format(folder), lineno, source)
            count = sum(1 for n in os.listdir(full)
                        if os.path.isfile(os.path.join(full, n)))
            self.env[stmt[4]] = count
            self.trace(lineno, source, "{} = {}".format(stmt[4], count))
            return

        if kind == "stop":
            self.trace(lineno, source, "stopping here")
            raise StopWorkflow()

        raise SayflowError("Internal error: unknown statement {!r}.".format(kind),
                           lineno, source)


# ---------------------------------------------------------------------------
# Sample data (used by reset_samples.py logic and the self-test)
# ---------------------------------------------------------------------------

SAMPLE_FILES = {
    "sample/inbox/invoice-march.txt": "Invoice #1042\nFrom: Studio North\nAmount due: $240\n",
    "sample/inbox/invoice-april.txt": "Invoice #1057\nFrom: Studio North\nAmount due: $180\n",
    "sample/inbox/meeting-notes.md": "# Sprint notes\n\n- Ship the triage demo\n- Book the venue\n",
    "sample/inbox/sales-2026.csv": "month,total\njan,1200\nfeb,1410\n",
    "sample/inbox/random-thoughts.txt": "Idea: a plant that waters itself.\n",
    "sample/reminders.txt": (
        "2026-10-27 | Call the dentist | urgent\n"
        "2026-10-26 | Send the wave report | \n"
        "2026-10-26 | Water the plants | \n"
        "2026-10-30 | Renew the library books | \n"
        "2026-10-28 | Fix the bike brakes | urgent\n"
        "2026-11-02 | Book train tickets | \n"
    ),
    "sample/messy.csv": (
        " name , email , city\n"
        " Ana Ruiz , ANA@example.com , sf\n"
        "ana ruiz,ana@example.com,SF\n"
        " Bob Lee , BOB@example.com , nyc\n"
        " , , \n"
        " Cara Diaz , CARA@example.com , la\n"
        "bob lee,bob@example.com,NYC\n"
    ),
}


def write_samples(base):
    for rel, content in SAMPLE_FILES.items():
        full = os.path.join(base, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as fh:
            fh.write(content)


# ---------------------------------------------------------------------------
# Self-test: runs all three examples in a throwaway sandbox and checks the
# results a user would actually see.
# ---------------------------------------------------------------------------


def selftest():
    here = os.path.dirname(os.path.abspath(__file__))
    failures = []

    def check(label, ok, detail=""):
        print("{} {}{}".format("PASS" if ok else "FAIL", label,
                               " — " + detail if detail else ""))
        if not ok:
            failures.append(label)

    tmp = tempfile.mkdtemp(prefix="sayflow-selftest-")
    try:
        write_samples(tmp)
        shutil.copytree(os.path.join(here, "examples"), os.path.join(tmp, "examples"))

        def run(name):
            path = os.path.join(tmp, "examples", name)
            with open(path, "r", encoding="utf-8") as fh:
                program = ProgramParser(fh.read()).parse()
            runner = Runner(tmp, quiet=True)
            runner.run(program)
            return runner

        run("file-triage.say")
        sorted_dir = os.path.join(tmp, "sample", "sorted")
        check("file-triage sorts invoices",
              sorted(os.listdir(os.path.join(sorted_dir, "invoices"))) ==
              ["invoice-april.txt", "invoice-march.txt"])
        check("file-triage sorts notes/data/other",
              os.listdir(os.path.join(sorted_dir, "notes")) == ["meeting-notes.md"] and
              os.listdir(os.path.join(sorted_dir, "data")) == ["sales-2026.csv"] and
              os.listdir(os.path.join(sorted_dir, "other")) == ["random-thoughts.txt"])
        check("file-triage empties the inbox",
              os.listdir(os.path.join(tmp, "sample", "inbox")) == [])

        run("reminder-digest.say")
        digest_path = os.path.join(tmp, "sample", "out", "digest.txt")
        digest = open(digest_path, encoding="utf-8").read() if os.path.isfile(digest_path) else ""
        check("reminder-digest groups urgent first",
              "URGENT (2):" in digest and "Call the dentist" in digest)
        check("reminder-digest groups today",
              "TODAY (2):" in digest and "Send the wave report" in digest)

        run("data-cleanup.say")
        clean_path = os.path.join(tmp, "sample", "out", "people-clean.txt")
        cleaned = open(clean_path, encoding="utf-8").read() if os.path.isfile(clean_path) else ""
        rows = [r for r in cleaned.splitlines() if r.strip()]
        check("data-cleanup dedupes and normalises rows",
              rows == ["Ana Ruiz | ana@example.com | SF",
                       "Bob Lee | bob@example.com | NYC",
                       "Cara Diaz | cara@example.com | LA"],
              "got: {}".format(rows))

        # Error handling: a nonsense line must fail with a friendly, lined error.
        try:
            ProgramParser('frobnicate the inbox\n').parse()
            check("parser rejects unknown lines", False)
        except SayflowError as err:
            check("parser rejects unknown lines", "Line 1" in err.render())

        # Sandbox escape must be refused.
        try:
            runner = Runner(tmp, quiet=True)
            runner.exec_stmt(("read", 1, 'read "../secret" into x',
                              ("lit", "../secret"), "x"))
            check("sandbox blocks path escapes", False)
        except SayflowError:
            check("sandbox blocks path escapes", True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if failures:
        print("\nSELFTEST FAILED: {} check(s)".format(len(failures)))
        return 1
    print("\nSELFTEST OK — all checks passed")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    flags = {a for a in argv[1:] if a.startswith("--")}
    root = os.getcwd()
    if "--root" in argv:
        idx = argv.index("--root")
        root = argv[idx + 1]
        args = [a for a in args if a != root]

    if "--selftest" in flags:
        return selftest()
    if not args:
        print(__doc__)
        return 2

    program_path = args[0]
    if not os.path.isfile(program_path):
        print("Sayflow: no such program file: {}".format(program_path))
        return 2
    with open(program_path, "r", encoding="utf-8") as fh:
        text = fh.read()
    try:
        program = ProgramParser(text).parse()
    except SayflowError as err:
        print("Sayflow couldn't read that program:")
        print(err.render())
        return 1
    if "--check" in flags:
        print("OK — {} parses cleanly ({} top-level statements).".format(
            program_path, len(program)))
        return 0
    runner = Runner(root, quiet="--quiet" in flags)
    try:
        runner.run(program)
    except SayflowError as err:
        print("Sayflow stopped:")
        print(err.render())
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
