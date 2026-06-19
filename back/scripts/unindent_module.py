"""
Script ponctuel : retire un niveau d'indentation sur un bloc de api.py.

Usage (depuis back/) :
  python scripts/unindent_module.py

Ne pas exécuter sur api.py actuel - conservé à titre d'archive pour référence.
"""

from pathlib import Path

API_PATH = Path(__file__).resolve().parent.parent / "api.py"


def main() -> None:
    lines = API_PATH.read_text(encoding="utf-8").splitlines(keepends=True)

    start, end = None, None
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith("app = ") or s.startswith("logging.basicConfig") and line.startswith("    "):
            if start is None:
                start = i
        if start is not None and s.startswith("def get_mongo_client"):
            end = i
            break
    if start is None:
        start = 34
    if end is None:
        end = 136

    result = []
    for i, line in enumerate(lines):
        if start <= i < end and line.startswith("    "):
            result.append(line[4:])
        else:
            result.append(line)

    API_PATH.write_text("".join(result), encoding="utf-8")
    print("Done")


if __name__ == "__main__":
    main()
