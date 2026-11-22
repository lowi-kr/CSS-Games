#!/usr/bin/env python3
"""Audit standalone HTML files for external resource dependencies."""
import base64, re, sys
from html.parser import HTMLParser
from pathlib import Path

class Audit(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.errors=[]; self.audio_nodes=0; self.audio_data=0; self.data_count=0
        self.script_depth=0; self.style_depth=0; self.script_text=[]
    def handle_starttag(self, tag, attrs):
        a=dict(attrs)
        if tag=="script":
            self.script_depth+=1
            if a.get("src") and not a["src"].startswith("data:"): self.errors.append("external script: "+a["src"])
        if tag=="style": self.style_depth+=1
        if tag in ("audio","embed"): self.audio_nodes+=1
        if tag in ("audio","video","source","embed","img","track","input"):
            src=a.get("src")
            if src:
                if not src.startswith("data:"): self.errors.append("non-embedded "+tag+" src: "+src)
                else:
                    self._data(src)
                    if tag in ("audio","embed") and src.lower().startswith("data:audio/"): self.audio_data+=1
        if tag=="video" and a.get("poster"):
            if not a["poster"].startswith("data:"): self.errors.append("non-embedded video poster")
            else: self._data(a["poster"])
        if tag=="link":
            rel=a.get("rel","").lower(); href=a.get("href","")
            if "stylesheet" in rel and not href.startswith("data:"): self.errors.append("external stylesheet: "+href)
            elif href and any(x in rel for x in ("icon","preload","manifest")) and not href.startswith("data:"): self.errors.append("external link resource: "+href)
        if a.get("srcset"):
            for item in a["srcset"].split(","):
                u=item.strip().split()[0]
                if not u.startswith("data:"): self.errors.append("non-embedded srcset: "+u)
                else: self._data(u)
        if a.get("style"): self._css(a["style"])
    def handle_endtag(self,tag):
        if tag=="script": self.script_depth=max(0,self.script_depth-1)
        if tag=="style": self.style_depth=max(0,self.style_depth-1)
    def handle_data(self,data):
        if self.script_depth: self.script_text.append(data)
        if self.style_depth: self._css(data)
    def _data(self,u):
        self.data_count+=1
        m=re.match(r"data:([^;,]+)(?:;[^,]*)?;base64,(.*)$",u,re.I|re.S)
        if not m: self.errors.append("malformed Base64 data URI"); return
        try: base64.b64decode(m.group(2),validate=True)
        except Exception: self.errors.append("invalid Base64 payload")
    def _css(self,s):
        if re.search(r"@import\b",s,re.I): self.errors.append("CSS @import remains")
        for u in re.findall(r"url\(\s*['\"]?([^)'\"\s]+)",s,re.I):
            if not u.startswith("data:") and not u.startswith("#"): self.errors.append("external CSS url: "+u)

pages=sorted(Path(".").rglob("*.html"))
css_files=sorted(Path(".").rglob("*.css"))
fail=[]; audio=embedded=resources=0
for p in pages:
    h=p.read_text(encoding="utf-8",errors="replace")
    if not re.search(r"<style\b",h,re.I): fail.append(str(p)+": no inline style")
    a=Audit()
    try: a.feed(h); a.close()
    except Exception as e: fail.append(str(p)+": parse error "+str(e))
    fail.extend(str(p)+": "+e for e in a.errors)
    audio+=a.audio_nodes; embedded+=a.audio_data; resources+=a.data_count
    for u in re.findall(r"https?://[^\s\"'<>]+", "\n".join(a.script_text)):
        fail.append(str(p)+": external URL in script "+u[:150])
if len(pages)!=17: fail.append("Expected 17 HTML files, found "+str(len(pages)))
if css_files: fail.append("CSS files remain: "+str(len(css_files)))
if audio==0: fail.append("No audio/embed elements detected")
if audio!=embedded: fail.append("Audio elements not Base64 embedded: "+str(audio-embedded))
print("HTML pages:",len(pages))
print("CSS files:",len(css_files))
print("Audio/embed elements:",audio,"; Base64 audio:",embedded)
print("Base64 resources checked:",resources)
if fail:
    print("OFFLINE AUDIT FAILED")
    for e in fail: print(" -",e)
    sys.exit(1)
print("OFFLINE AUDIT PASSED")
