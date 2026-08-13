from __future__ import annotations

# This table is the ONLY source of commands this module can ever run. A caller
# supplies a symbolic `name`; that name is used solely as a lookup key here and
# never contributes to, nor is concatenated into, the argv that gets executed.
# This is starting scaffolding, not a complete toolset: it ships with a handful
# of small, read-only, informational commands as an example. Extend it with
# your own fixed argv lists as needed, but keep every entry non-destructive —
# this module intentionally has no path for arbitrary or user-influenced code
# execution, and entries should preserve that guarantee.
#
# Each value is either:
#   - a fixed argv list (list[str]), used on any OS, or
#   - a dict mapping platform.system() values ("Linux", "Windows", "Darwin")
#     to the fixed argv list for that OS, when the command differs per OS.

WHITELIST: dict[str, list[str] | dict[str, list[str]]] = {
    "list_home_dir": ["ls", "-la"],
    "uptime": ["uptime"],
    "disk_usage": {
        "Linux": ["df", "-h"],
        "Darwin": ["df", "-h"],
        "Windows": ["wmic", "logicaldisk", "get", "size,freespace,caption"],
    },
}
