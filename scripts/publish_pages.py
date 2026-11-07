#!/usr/bin/env python3
"""Publish the dashboard (out/index.html, the viewer, the design notes) to GitHub Pages.

  scripts/publish_pages.py            assemble build/pages/ and show what would go
  scripts/publish_pages.py --push     also commit it to the gh-pages branch and push

The site is out/ as `proj up simple_earring` serves it, minus scratch files: out/viewer/
and out/docs/ are copied whole; everything else is copied only if the dashboard (or a
page it links) references it, found by following local src/href links from index.html.
Paths in EXCLUDE never go, and links to anything left out are dropped from the copied
pages so the site has no dead links. Don't hold data back on a guess that it's private:
ask the user.

gh-pages holds only the site (one commit per publish, on top of the last), the way
round-pendant publishes. Run `python3 scripts/render.py --index-only` and rebuild the
viewer first; this copies what is on disk.
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out"
SITE = ROOT / "build" / "pages"
WHOLE = ["viewer", "docs"]
# nothing is held back today; add an out/-relative path here to keep it off the public site
EXCLUDE = []
REF = re.compile(r'(?:src|href)="([^"]+)"')


def _local(ref):
    return not (ref.startswith(("#", "/", "mailto:", "data:", "javascript:"))
                or "://" in ref or ref.startswith("${"))


def _excluded(rel):
    return any(rel == e or rel.startswith(e + "/") for e in EXCLUDE)


def _target(page, ref):
    """out/-relative path a ref on `page` (out/-relative) points at, or None."""
    ref = ref.split("#")[0].split("?")[0]
    if not ref:
        return None
    p = (OUT / page).parent / ref
    try:
        rel = p.resolve().relative_to(OUT.resolve())
    except ValueError:
        return None
    if (OUT / rel).is_dir():
        rel = rel / "index.html"
    return rel.as_posix()


def assemble():
    if SITE.exists():
        shutil.rmtree(SITE)
    SITE.mkdir(parents=True)
    for d in WHOLE:
        shutil.copytree(OUT / d, SITE / d)
    todo, seen = ["index.html"], set()
    while todo:
        rel = todo.pop()
        if rel in seen or _excluded(rel) or not (OUT / rel).is_file():
            continue
        seen.add(rel)
        dst = SITE / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(OUT / rel, dst)
        if rel.endswith(".html") and not rel.startswith(tuple(w + "/" for w in WHOLE)):
            for ref in REF.findall((OUT / rel).read_text(errors="replace")):
                if _local(ref) and (t := _target(rel, ref)):
                    todo.append(t)
    # drop links to what was left out
    dropped = []
    for page in SITE.rglob("*.html"):
        rel = page.relative_to(SITE).as_posix()
        if rel.startswith(tuple(w + "/" for w in WHOLE)):
            continue
        s = page.read_text(errors="replace")

        def gone(m):
            t = _target(rel, m.group(1))
            return t is not None and _local(m.group(1)) and not (SITE / t).exists()

        n = s
        for li in re.findall(r"<li>.*?</li>", s, re.S):
            m = re.search(r'href="([^"]+)"', li)
            if m and gone(m):
                n = n.replace(li, "")
                dropped.append(f"{rel}: {m.group(1)}")
        page.write_text(n)
    (SITE / ".nojekyll").write_text("")
    size = sum(f.stat().st_size for f in SITE.rglob("*") if f.is_file())
    print(f"site: {SITE.relative_to(ROOT)}, {len(list(SITE.rglob('*')))} entries, "
          f"{size / 1e6:.1f} MB")
    for d in dropped:
        print(f"  dropped link {d}")
    return SITE


def push():
    git = lambda *a, **k: subprocess.run(["git", *a], cwd=ROOT, check=True, **k)
    wt = ROOT / "build" / "gh-pages"
    if wt.exists():
        git("worktree", "remove", "--force", str(wt))
    git("fetch", "-q", "origin")
    have = subprocess.run(["git", "ls-remote", "--exit-code", "--heads", "origin", "gh-pages"],
                          cwd=ROOT, capture_output=True).returncode == 0
    if have:
        git("worktree", "add", "-q", "-B", "gh-pages", str(wt), "origin/gh-pages")
    else:
        git("worktree", "add", "-q", "--detach", str(wt))
        subprocess.run(["git", "checkout", "-q", "--orphan", "gh-pages"], cwd=wt, check=True)
    for p in wt.iterdir():
        if p.name != ".git":
            shutil.rmtree(p) if p.is_dir() else p.unlink()
    shutil.copytree(SITE, wt, dirs_exist_ok=True)
    subprocess.run(["git", "add", "-A"], cwd=wt, check=True)
    head = subprocess.run(["git", "log", "-1", "--format=%h"], cwd=ROOT,
                          capture_output=True, text=True).stdout.strip()
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=wt).returncode == 0:
        print("gh-pages: no change")
    else:
        subprocess.run(["git", "commit", "-q", "-m", f"Publish the dashboard from {head}"],
                       cwd=wt, check=True)
        subprocess.run(["git", "push", "-q", "origin", "gh-pages"], cwd=wt, check=True)
        print("gh-pages: pushed")
    git("worktree", "remove", "--force", str(wt))


if __name__ == "__main__":
    assemble()
    if "--push" in sys.argv:
        push()
