#!/usr/bin/env python3
"""Embed remotely hosted static resources into standalone HTML pages."""
import base64, io, math, mimetypes, random, re, struct, sys, wave
from pathlib import Path
from urllib.parse import urlparse
import requests

MAX_BYTES = 20 * 1024 * 1024
S = requests.Session()
S.headers["User-Agent"] = "CSS-Games-Offline-Builder/1.0"
CACHE, FAILED, GENERATED, COUNT = {}, set(), set(), 0

def make_audio_fallback(url):
    """Generate a small offline substitute when the original studiokah MP3 is gone."""
    name = url.rsplit("/", 1)[-1].lower()
    rate = 22050
    duration = 0.16 if "click" in name else (0.45 if "dice" in name else 0.85)
    midi = 48
    piano = re.search(r"keyboard-32-(\d+)\.mp3$", name)
    if piano: midi = 48 + int(piano.group(1))
    freq = 440.0 * (2 ** ((midi - 69) / 12))
    rng = random.Random(name)
    raw = io.BytesIO()
    with wave.open(raw, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        frames = bytearray()
        for i in range(int(rate * duration)):
            t = i / rate
            if piano:
                env = math.exp(-4.2 * t)
                sample = sum(math.sin(2 * math.pi * freq * h * t) / (h ** 1.35) for h in (1,2,3,4,5))
                sample *= env * 0.58
            else:
                env = math.exp(-35 * t)
                noise = (rng.random() * 2 - 1)
                tone = math.sin(2 * math.pi * (1800 if "click" in name else 430) * t)
                sample = (noise * 0.45 + tone * 0.55) * env
            sample = max(-1, min(1, sample))
            frames.extend(struct.pack("<h", int(sample * 30000)))
        w.writeframes(frames)
    return raw.getvalue()

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
        # These old sound URLs are all returning 404. Keep the interactions audible
        # with generated local WAV tones/effects rather than leaving network requests.
        if url.startswith("https://studiokah.com/tests/") and url.lower().endswith(".mp3"):
            payload = make_audio_fallback(url)
            CACHE[url] = (payload, "audio/wav"); GENERATED.add(url)
            print("Generated offline audio substitute for", url)
            return CACHE[url]
        FAILED.add(url); print("FAILED", url, e, file=sys.stderr); return None

def data(url):
    item = fetch(url)
    return "data:" + item[1] + ";base64," + base64.b64encode(item[0]).decode() if item else url

def css(text, depth=0):
    if depth > 8: return text
    imp = re.compile(r'@import\s+(?:url\(\s*)?(["\']?)(https?://[^"\')\s;]+|//[^"\')\s;]+)\1\s*\)?\s*([^;]*);', re.I)
    def do_import(m):
        item = fetch(m.group(2))
        if not item or ("css" not in item[1] and not m.group(2).lower().split("?")[0].endswith(".css")): return m.group(0)
        imported = css(item[0].decode("utf-8", "replace"), depth + 1)
        media = m.group(3).strip()
        return imported if not media else "@media " + media + " {\n" + imported + "\n}"
    text = imp.sub(do_import, text)
    url_re = re.compile(r'url\(\s*(["\']?)(https?://[^"\')]+|//[^"\')]+)\1\s*\)', re.I)
    return url_re.sub(lambda m: "url('" + data(m.group(2)) + "')" if fetch(m.group(2)) else m.group(0), text)

def rewrite_tag(t):
    if re.match(r'<link\b', t, re.I) and re.search(r'rel\s*=\s*["\'][^"\']*stylesheet', t, re.I):
        m = re.search(r'(?:href|ref)\s*=\s*(["\'])(https?://.*?)\1', t, re.I)
        if m:
            item = fetch(m.group(2))
            if item: return "<style>\n" + css(item[0].decode("utf-8", "replace")) + "\n</style>"
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

def process(path):
    h=path.read_text(encoding="utf-8",errors="replace")
    script_re=re.compile(r'<script\b([^>]*?)\bsrc\s*=\s*(["\'])(https?://.*?)\2([^>]*)>\s*</script\s*>',re.I|re.S)
    def inline_script(m):
        item=fetch(m.group(3))
        if not item: return m.group(0)
        return "<script"+m.group(1)+m.group(4)+">\n"+item[0].decode("utf-8","replace")+"\n</script>"
    h=script_re.sub(inline_script,h)
    h=re.sub(r'(<style\b[^>]*>)(.*?)(</style\s*>)',lambda m:m.group(1)+css(m.group(2))+m.group(3),h,flags=re.I|re.S)
    h=re.sub(r'<(?:link|img|audio|video|source|embed|track|input)\b[^>]*>',lambda m:rewrite_tag(m.group(0)),h,flags=re.I|re.S)
    return h

pages=sorted(Path(".").rglob("*.html"))
if not pages: raise SystemExit("No HTML pages found")
done=[]
for p in pages:
    h=process(p); p.write_text(h,encoding="utf-8"); done.append((p,h))
css_files = sorted(Path(".").rglob("*.css"))
for css_file in css_files:
    css_file.unlink()
left=[]
for p,h in done:
    for n,line in enumerate(h.splitlines(),1):
        for m in re.finditer(r'https?://[^\s"\'<>)]+' ,line):
            u=m.group(0).rstrip(".,;")
            if "data:" not in u and "www.w3.org/" not in u: left.append(f"{p}:{n}: {u[:220]}")
report=["# Offline build report","",f"- HTML pages processed: {len(pages)}",f"- CSS files removed: {len(css_files)}",f"- Unique resources downloaded: {COUNT}",f"- Base64 audio resources: {sum(h.count('data:audio/') for _,h in done)}",f"- Offline audio substitutes generated: {len(GENERATED)}",f"- Failed downloads: {len(FAILED)}",f"- Remaining absolute URL occurrences: {len(left)}","",
"Remaining URLs may be navigation links, dynamic JavaScript/API calls, blocked resources, or services that cannot be embedded. Audio substitutes are generated WAV tones/effects because the original MP3 endpoints returned 404. Review before claiming full offline support.","","## Generated audio substitutes"]+[f"- {u}" for u in sorted(GENERATED)]+["","## Failed downloads"]+[f"- {u}" for u in sorted(FAILED)]+["","## Remaining URLs"]+[f"- {x}" for x in left]
Path("OFFLINE-BUILD-REPORT.md").write_text("\n".join(report)+"\n",encoding="utf-8")
print(f"Processed {len(pages)} HTML files; downloaded {COUNT}; generated {len(GENERATED)} audio fallbacks; failed {len(FAILED)}.")
