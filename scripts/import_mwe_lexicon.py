#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from collections.abc import Iterator
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.english_learning import lexicon
from modules.english_learning.domain import LexiconEntry

_TIMEOUT = httpx.Timeout(60.0, read=300.0)


def _stream_remote(pos: str) -> Iterator[LexiconEntry]:
    url = lexicon.kaikki_url(pos)
    print(f"→ {url}", flush=True)
    with httpx.stream("GET", url, timeout=_TIMEOUT, follow_redirects=True) as response:
        response.raise_for_status()
        seen = 0
        for line in response.iter_lines():
            seen += 1
            if seen % 50_000 == 0:
                print(f"  {pos}: {seen} записей просмотрено", flush=True)
            yield from lexicon.entries_from_jsonl([line])


def _read_local(path: Path) -> Iterator[LexiconEntry]:
    print(f"→ {path}", flush=True)
    with path.open(encoding="utf-8") as handle:
        yield from lexicon.entries_from_jsonl(handle)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Импорт идиом и фразовых глаголов из Wiktionary (kaikki.org) в english_mwe_lexicon."
    )
    parser.add_argument("--file", type=Path, action="append", default=[], help="локальный kaikki .jsonl (можно несколько)")
    parser.add_argument("--with-nouns-adjs", action="store_true", help="также noun и adj (ещё ~2.2 ГБ трафика)")
    args = parser.parse_args()

    entries: list[LexiconEntry] = []
    if args.file:
        for path in args.file:
            entries.extend(_read_local(path))
    else:
        parts = lexicon.KAIKKI_DEFAULT_POS + (lexicon.KAIKKI_EXTRA_POS if args.with_nouns_adjs else ())
        for pos in parts:
            before = len(entries)
            entries.extend(_stream_remote(pos))
            print(f"  {pos}: +{len(entries) - before} выражений", flush=True)
    count = lexicon.store(entries)
    print(f"Готово: {count} выражений в словаре. Источник: {lexicon.KAIKKI_ATTRIBUTION}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
