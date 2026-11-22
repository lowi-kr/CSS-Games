#!/usr/bin/env python3
"""Embed remotely hosted static resources into standalone HTML pages."""
import base64, mimetypes, re, sys
from pathlib import Path
from urllib.parse import urlparse
import requests

MAX_BYTES = 20 * 1024 * 1024
S = requests.Session()
S.headers["User-Agent"] = "CSS-Games-Offline-Builder/1.0"
CACHE, FAILED, COUNT = {}, set(), 0

def fetch(url):
    global COUNT
    url = "https:" + url if url.startswith("//") else url
    if url in CACHE: return CACHE[url]
    if url in FAILED: return None
    try:
        r = S.get(url, timeout=35); r.raise_for_status()
        if len(r.content) > MAX_BYTES: raise ValueError("over 20 MiB limit")
        kind = r.headers.get("content-type", "").split(";")[0].strip() or mimetypes.guess_type(urlparse(url).path)[0] or "application/octet-stream"
        CACHE[url] = (r.content, kind); COUNT += 1
        print("Downloaded", url, len(r.content), "bytes")
        return CACHE[url]
    except Exception as e:
        FAILED.add(url); print("FAILED", url, e, file=sys.stderr); return None

def data(url):
    item = fetch(url)
    return "data:" + item[1] + ";base64," + base64.b64encode(item[0]).decode() if item else url

def css(css, depth=0):
    if depth > 8: return css
    imp = re.compile(r'@import\s+(?:url\(\s*)?(["\']?)(https?://[^"\')\s;]+|//[^"\')\s;]+)\1\s*\)?\s*([^;]*);', re.I)
    def do_import(m):
        item = fetch(m.group(2))
        if not item or ("css" not in item[1] and not m.group(2).lower().split("?")[0].endswith(".css")): return m.group(0)
        return css(item[0].decode("utf-8", "replace"), depth + 1)
    css = imp.sub(do_import, css)
    url_re = re.compile(r'url\(\s*(["\']?)(https?://[^"\')]+|//[^"\')]+)\1\s*\)', re.I)
    return url_re.sub(lambda m: "url('" + data(m.group(2)) + "')" if fetch(m.group(2)) else m.group(0), css)

def tag(t):
    if re.match(r'<link\b', t, re.I) and re.search(r'rel\s*=\s*["\'][^"\']*stylesheet', t, re.I):
        m = re.search(r'href\s*=\s*(["\'])(https?://.*?)\1', t, re.I)
        if m:
            item = fetch(m.group(2))
            if item: return "<style>\n" + css(item[0].decode("utf-8", "replace")) + "\n</style>"
    if re.match(r'<script\b', t, re.I):
        m = re.search(r'\bsrc\s*=\s*(["\'])(https?://.*?)\1', t, re.I)
        if m:
            item = fetch(m.group(2))
            if item:
                attrs = re.sub(r'\s+src\s*=\s*(["\']).*?\1', '', t, flags=re.I)
                return re.sub(r'\s*/?>$', '', attrs) + ">\n" + item[0].decode("utf-8", "replace") + "\n</script>"
    mt = re.match(r'<\s*([a-zA-Z0-9:-]+)', t); name = mt.group(1).lower() if mt else ""
    if name in {"img","audio","video","source","embed","track","input"}:
        t = re.sub(r'\b(src|poster)\s*=\s*(["\'])(https?://.*?)\2', lambda m: m.group(1)+"="+m.group(2)+data(m.group(3))+m.group(2), t, flags=re.I)
        def srcset(m):
            out=[]
            for e in m.group(2).split(","):
                p=e.strip().split()
                if p and p[0].startswith(("http://","https://","//")): p[0]=data(p[0])
                out.append(" ".join(p))
            return "srcset="+m.group(1)+", ".join(out)+m.group(1)
        t = re.sub(r'\bsrcset\s*=\s*(["\'])(.*?)\1', srcset, t, flags=re.I)
    return re.sub(r'\bstyle\s*=\s*(["\'])(.*?)\1', lambda m:"style="+m.group(1)+css(m.group(2))+m.group(1), t, flags=re.I|re.S)

pages=sorted(Path(".").rglob("*.html"))
if not pages: raise SystemExit("No HTML pages found")
done=[]
for p in pages:
    h=p.read_text(encoding="utf-8",errors="replace")
    h=re.sub(r'(<style\b[^>]*>)(.*?)(</style\s*>)',lambda m:m.group(1)+css(m.group(2))+m.group(3),h,flags=re.I|re.S)
    h=re.sub(r'<[^>]+>',lambda m:tag(m.group(0)),h)
    p.write_text(h,encoding="utf-8"); done.append((p,h))
left=[]
for p,h in done:
    for n,line in enumerate(h.splitlines(),1):
        for m in re.finditer(r'https?://[^\s"\'<>)]+' ,line):
            u=m.group(0).rstrip(".,;")
            if "data:" not in u and "www.w3.org/" not in u: left.append(f"{p}:{n}: {u[:220]}")
report=["# Offline build report","",f"- HTML pages processed: {len(pages)}",f"- Unique resources downloaded: {COUNT}",f"- Failed downloads: {len(FAILED)}",f"- Remaining absolute URL occurrences: {len(left)}","",
"Remaining URLs may be navigation links, dynamic JavaScript/API calls, blocked resources, or services that cannot be embedded. Review before claiming full offline support.","","## Failed downloads"]+[f"- {u}" for u in sorted(FAILED)]+["","## Remaining URLs"]+[f"- {x}" for x in left]
Path("OFFLINE-BUILD-REPORT.md").write_text("\n".join(report)+"\n",encoding="utf-8")
print(f"Processed {len(pages)} HTML files; embedded {COUNT}; failed {len(FAILED)}.")
