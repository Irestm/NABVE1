from __future__ import annotations

import re

# Minimal recursive-descent parser for Valve's KeyValues ("VDF") text format,
# just enough for the two file kinds Steam actually gives us here —
# libraryfolders.vdf and appmanifest_*.acf: quoted string keys/values and
# nested {} blocks. Not the full VDF spec (no #include, no conditionals,
# no unquoted tokens) — those don't appear in either file kind.
_TOKEN_RE = re.compile(r'"(?:[^"\\]|\\.)*"|[{}]')


def _tokenize(text: str) -> list[str]:
    return [match.group(0) for match in _TOKEN_RE.finditer(text)]


def _unquote(token: str) -> str:
    return token[1:-1].replace('\\"', '"').replace("\\\\", "\\")


def parse_vdf(text: str) -> dict[str, object]:
    """Parses VDF `text` into nested dicts (string values, or nested dicts
    for {} blocks). Raises ValueError on structurally broken input (e.g. a
    key with nothing after it) rather than silently returning a partial
    tree — callers should catch it and treat the file as unusable, same as
    an OSError reading it."""
    tokens = _tokenize(text)
    pos = 0

    def parse_block(require_closing_brace: bool) -> dict[str, object]:
        # `require_closing_brace` distinguishes a block actually opened by a
        # "{" (nested, or the outer root-key wrap below) — which must see a
        # matching "}" or the input was truncated — from the bare top-level
        # document (no enclosing braces at all), where running out of
        # tokens is just the normal end of input. Without this distinction,
        # a genuinely truncated nested block (e.g. a Steam file cut off
        # mid-write) silently returned whatever had been parsed so far
        # instead of raising, contradicting this function's own contract —
        # worse, tokens after the truncation point could get folded into
        # the wrong (still-"open") dict instead of being rejected.
        nonlocal pos
        result: dict[str, object] = {}
        while True:
            if pos >= len(tokens):
                if require_closing_brace:
                    raise ValueError("Unexpected end of input: missing a closing '}'")
                return result
            token = tokens[pos]
            if token == "}":
                pos += 1
                return result
            if token == "{":
                raise ValueError("Unexpected '{' without a preceding key")
            key = _unquote(token)
            pos += 1
            if pos >= len(tokens):
                raise ValueError(f"Key '{key}' has no value or block")
            if tokens[pos] == "{":
                pos += 1
                result[key] = parse_block(require_closing_brace=True)
            elif tokens[pos] == "}":
                raise ValueError(f"Key '{key}' has no value or block")
            else:
                result[key] = _unquote(tokens[pos])
                pos += 1

    if not tokens:
        return {}

    # Both file kinds are shaped as one root key wrapping a single {} block
    # ("libraryfolders" { ... } / "AppState" { ... }) rather than a bare
    # block — unwrap it so callers don't need to know the root key's name.
    if tokens[0] not in ("{", "}") and len(tokens) > 1 and tokens[1] == "{":
        root_key = _unquote(tokens[0])
        pos = 2
        return {root_key: parse_block(require_closing_brace=True)}

    return parse_block(require_closing_brace=False)


def find_all_values(data: object, key: str) -> list[str]:
    """Every string value stored under `key` anywhere in the (possibly
    nested) parse tree — used for libraryfolders.vdf, where each library's
    "path" sits under an arbitrary numeric index key ("0", "1", ...) whose
    exact names aren't worth modeling."""
    found: list[str] = []
    if isinstance(data, dict):
        for child_key, value in data.items():
            if child_key == key and isinstance(value, str):
                found.append(value)
            else:
                found.extend(find_all_values(value, key))
    return found


def find_value(data: object, key: str) -> str | None:
    values = find_all_values(data, key)
    return values[0] if values else None
