"""Checks the published site before a push.

    python3 scripts/check-site.py

  1. Every local link (href/src) in every HTML page resolves to a file; a #fragment points to an id on that page.
  2. Every page under ai-capability-check/ is listed in sitemap.xml, and every sitemap URL under the site exists.
  3. Every hreflang alternate is reciprocal: the page it points to links back to the page with the same set.
  4. No analytics or tag-manager code on the pages (the site has no tracking).
Exit 1 on any problem.
"""
import glob
import os
import re
import sys
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

SITE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
BASE = "https://simplicity-io.github.io"
TRACKING = re.compile(r"googletagmanager|gtag\(|google-analytics|googleanalytics|fbq\(|hotjar|clarity\.ms", re.I)


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids, self.links, self.alts = set(), [], []

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if "id" in d:
            self.ids.add(d["id"])
        if tag == "a" and "name" in d:
            self.ids.add(d["name"])
        for k in ("href", "src"):
            if k in d and d[k]:
                self.links.append(d[k])
        if tag == "link" and d.get("rel") == "alternate" and "hreflang" in d:
            self.alts.append((d["hreflang"], d["href"]))


def parse(path):
    p = Page()
    with open(path, encoding="utf-8") as f:
        p.feed(f.read())
    return p


def page_file(url):
    """Local file for a site URL (https://simplicity-io.github.io/x/ -> x/index.html)."""
    if not url.startswith(BASE):
        return None
    rel = url[len(BASE):].split("#")[0].split("?")[0]
    if rel.endswith("/") or rel == "":
        rel += "index.html"
    return os.path.join(SITE, rel.lstrip("/"))


def main():
    problems = 0

    def fail(msg):
        nonlocal problems
        problems += 1
        print(msg)

    pages = {}
    for path in glob.glob(os.path.join(SITE, "**", "*.html"), recursive=True):
        pages[os.path.normpath(path)] = parse(path)

    # 1. Local links and fragments.
    for path, p in pages.items():
        rel = os.path.relpath(path, SITE)
        for link in p.links:
            if link.startswith(("http://", "https://", "mailto:", "tel:", "data:", "javascript:")):
                continue
            base, _, frag = link.partition("#")
            if not base:
                if frag and frag not in p.ids:
                    fail("%s: #%s not found on this page" % (rel, frag))
                continue
            clean = base.split("?")[0]
            if clean.startswith("/"):                 # root-relative: from the site root
                target = os.path.normpath(os.path.join(SITE, clean.lstrip("/")))
            else:
                target = os.path.normpath(os.path.join(os.path.dirname(path), clean))
            if base.endswith("/"):
                target = os.path.join(target, "index.html")
            if not os.path.exists(target):
                fail("%s: broken link %s" % (rel, link))
                continue
            if frag and target.endswith(".html"):
                tp = pages.get(os.path.normpath(target)) or parse(target)
                if frag not in tp.ids:
                    fail("%s: %s has no id #%s" % (rel, link, frag))

    # 2. Sitemap coverage.
    sitemap = os.path.join(SITE, "sitemap.xml")
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    locs = [e.text.strip() for e in ET.parse(sitemap).getroot().findall("s:url/s:loc", ns)]
    for loc in locs:
        f = page_file(loc)
        if f and not os.path.exists(f):
            fail("sitemap: %s has no file" % loc)
    for path in pages:
        rel = os.path.relpath(path, SITE)
        if rel.startswith("ai-capability-check" + os.sep) and rel.endswith("index.html"):
            url = BASE + "/" + rel[:-len("index.html")].replace(os.sep, "/")
            if url not in locs:
                fail("sitemap: %s is missing" % url)

    # 3. Reciprocal hreflang.
    for path, p in pages.items():
        if not p.alts:
            continue
        mine = {u for _, u in p.alts}
        rel = os.path.relpath(path, SITE)
        for lang, u in p.alts:
            f = page_file(u)
            if not f or not os.path.exists(f):
                fail("%s: hreflang %s points to a missing page %s" % (rel, lang, u))
                continue
            other = pages.get(os.path.normpath(f)) or parse(f)
            if not mine <= {x for _, x in other.alts}:
                fail("%s: %s does not list all alternates back" % (os.path.relpath(f, SITE), rel))

    # 4. No tracking code.
    for path in pages:
        with open(path, encoding="utf-8") as f:
            if TRACKING.search(f.read()):
                fail("%s: tracking/analytics code found" % os.path.relpath(path, SITE))

    if problems:
        print("%d problem(s)" % problems)
        sys.exit(1)
    print("OK: %d pages, %d sitemap URLs checked." % (len(pages), len(locs)))


if __name__ == "__main__":
    main()
