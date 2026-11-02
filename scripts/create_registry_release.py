#!/usr/bin/env python3
"""Emit tagged CI release manifest with exact file hashes; no signing occurs here."""
import hashlib
import json
import os
from pathlib import Path
import re
import sys
product,platform,directory=sys.argv[1:4]
tag=os.getenv("GITHUB_REF_NAME","")
repository=os.getenv("GITHUB_REPOSITORY","")
commit=os.getenv("GITHUB_SHA","")
if not re.fullmatch(r"v\d+\.\d+\.\d+",tag) or not re.fullmatch(r"[a-f0-9]{40}",commit) or repository.lower()!=f"tabenius/{product}":
    raise SystemExit("A source-bound immutable version tag is required")
root=Path(directory)
if not root.is_dir(): raise SystemExit("Release artifact directory is missing")
files=[]
for path in sorted(root.iterdir()):
    if path.name in ("release.json","release.sigstore.json"): continue
    if not path.is_file() or path.is_symlink() or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,119}",path.name):
        raise SystemExit("Invalid candidate file")
    size=path.stat().st_size
    if not 0<size<=4*1024**3: raise SystemExit("Refused candidate file size")
    digest=hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024*1024),b""): digest.update(chunk)
    files.append({"name":path.name,"path":f"releases/{product}/{tag[1:]}/{platform}/{path.name}","sha256":digest.hexdigest(),"bytes":size})
if not 1<=len(files)<=32: raise SystemExit("Invalid release file count")
manifest={"schema":"ragbaz.release/1","repository":repository,"product":product,"version":tag[1:],"platform":platform,"channel":"candidate","sourceCommit":commit,"files":files}
with (root/"release.json").open("x",encoding="utf8") as out:
    json.dump(manifest,out,indent=2)
    out.write("\n")
