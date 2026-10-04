"""Point every install command and manifest at your GitHub repository.

    python scripts/set_repo.py your-name/recall

Replaces the YOUR-GITHUB-USER/recall placeholder in pyproject.toml and the docs, then
regenerates the plugin manifests (`recall export-repo`). Run it once after forking or
before your first push; run it again if you rename the repository.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES = ["pyproject.toml", "README.md", "CONTRIBUTING.md", os.path.join("docs", "UNINSTALL.md")]
SLUG = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$")


def main() -> int:
    if len(sys.argv) != 2 or not SLUG.match(sys.argv[1]):
        print(__doc__)
        return 2
    new = sys.argv[1]
    sys.path.insert(0, os.path.join(ROOT, "src"))
    from recall.integrations.repo import PLACEHOLDER, export_repo, read_slug

    old = read_slug(os.path.join(ROOT, "pyproject.toml"))
    for rel in FILES:
        path = os.path.join(ROOT, rel)
        with open(path, encoding="utf-8") as f:
            text = f.read()
        for before in {old, PLACEHOLDER}:
            text = text.replace(f"github.com/{before}", f"github.com/{new}").replace(before, new)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    written = export_repo(ROOT, new)
    print(f"now pointing at https://github.com/{new}: updated {len(FILES)} docs and {len(written)} manifests")
    return 0


if __name__ == "__main__":
    sys.exit(main())
