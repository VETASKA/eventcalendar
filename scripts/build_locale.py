"""Builds locale/{en,pl}/LC_MESSAGES/django.po + .mo from locale/public.json and checks nothing is missing.

    python scripts/build_locale.py          # needs `pip install babel` (dev only); the .mo files are committed

Ukrainian is the source language (msgid), so there is no uk catalog. Every {% translate %} / _() string of the
public site must have an entry in locale/public.json — the script lists the missing ones and fails.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES = [*sorted((ROOT / "apps/public/templates").rglob("*.html")), *sorted((ROOT / "apps/public").glob("*.py")),
           *sorted((ROOT / "apps/subscriptions/templates").rglob("*.html")),
           *sorted((ROOT / "apps/subscriptions").glob("*.py")), *sorted((ROOT / "templates/email").rglob("*.*"))]


def used_ids() -> list[str]:
    ids: list[str] = []
    for f in SOURCES:
        if not f.exists():
            continue
        t = f.read_text()
        found = re.findall(r'\{% translate "((?:[^"\\]|\\.)*)"', t)
        found += [re.sub(r"\{\{ (\w+) \}\}", r"%(\1)s", m)
                  for m in re.findall(r"\{% blocktranslate[^%]*%\}(.*?)\{% endblocktranslate %\}", t, re.S)]
        found += ["".join(re.findall(r'"((?:[^"\\]|\\.)*)"', m))
                  for m in re.findall(r'(?<![\w.])_\(\s*((?:"(?:[^"\\]|\\.)*"\s*)+)\)', t)]
        ids += [i for i in found if i not in ids]
    return ids


def esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def main() -> int:
    data = json.loads((ROOT / "locale/public.json").read_text())
    missing = [i for i in used_ids() if i not in data]
    if missing:
        print("missing in locale/public.json:\n  " + "\n  ".join(missing))
        return 1
    plural = {"en": "nplurals=2; plural=(n != 1);",
              "pl": "nplurals=3; plural=(n==1 ? 0 : n%10>=2 && n%10<=4 && (n%100<10 || n%100>=20) ? 1 : 2);"}
    for code in ("en", "pl"):
        d = ROOT / "locale" / code / "LC_MESSAGES"
        d.mkdir(parents=True, exist_ok=True)
        out = ['msgid ""', 'msgstr ""', '"Content-Type: text/plain; charset=UTF-8\\n"', f'"Language: {code}\\n"',
               f'"Plural-Forms: {plural[code]}\\n"', ""]
        for k, v in data.items():
            out += [f'msgid "{esc(k)}"', f'msgstr "{esc(v[code])}"', ""]
        (d / "django.po").write_text("\n".join(out))
        subprocess.run(["pybabel", "compile", "-d", str(ROOT / "locale"), "-D", "django", "-l", code], check=True,
                       capture_output=True)
    print(f"ok: {len(data)} strings × en, pl")
    return 0


if __name__ == "__main__":
    sys.exit(main())
