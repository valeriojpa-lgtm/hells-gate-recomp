#!/usr/bin/env python3
"""Turn a Dante's Inferno runtime log into conservative preservation gate evidence."""
from __future__ import annotations
import argparse, json, re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

TU_RE=re.compile(r"XEX patch applied successfully: base version:\s*([0-9.]+),\s*new version:\s*([0-9.]+)",re.I)
UNRESOLVED_PATTERNS=(
 re.compile(r"Call to (?:unresolved|invalid or unregistered) function at guest address 0x([0-9A-Fa-f]{8})",re.I),
 re.compile(r"Unresolved (?:call|branch) from 0x[0-9A-Fa-f]{8} to 0x([0-9A-Fa-f]{8})",re.I),
)
SWAP_RE=re.compile(r"\[GPU SwapGuest\].*?ptr=0x([0-9A-Fa-f]+).*?bytes=(\d+).*?nonzero=(\d+).*?hash=0x([0-9A-Fa-f]+)",re.I)
VDSWAP_RE=re.compile(r"\bVdSwap:.*?(\d+)x(\d+)",re.I)
VFETCH_RE=re.compile(r"\bVFETCH-OOB\b",re.I)
REGISTER_RE=re.compile(r"\bregistered\s+([0-9][0-9,._ ]*)\s+functions\b",re.I)
FIBER_RE=re.compile(r"Q01 FIBER: cleared TU2 callback slot 0x82CE68E4",re.I)
ACCESS_RE=re.compile(r"(?:Unhandled guest access violation|Access violation faulting PC|EXCEPTION_ACCESS_VIOLATION)",re.I)

@dataclass
class Gate:
    id:str; status:str; summary:str; evidence:list[str]

def unresolved_targets(data:str)->Counter[int]:
    counts=Counter()
    for line in data.splitlines():
        for p in UNRESOLVED_PATTERNS:
            m=p.search(line)
            if m: counts[int(m.group(1),16)]+=1; break
    return counts

def report(data:str)->dict:
    tus=TU_RE.findall(data); tu_ok=any(a=="0.0.0.1" and b=="0.0.2.1" for a,b in tus)
    unresolved=unresolved_targets(data); total=sum(unresolved.values())
    swaps=[{"ptr":f"0x{int(m.group(1),16):08X}","bytes":int(m.group(2)),"nonzero":int(m.group(3)),"hash":"0x"+m.group(4).upper()} for m in SWAP_RE.finditer(data)]
    nonzero=[s for s in swaps if s["nonzero"]>0]; vds=[(int(a),int(b)) for a,b in VDSWAP_RE.findall(data)]
    regs=[int(re.sub(r"[^0-9]","",m.group(1))) for m in REGISTER_RE.finditer(data) if re.sub(r"[^0-9]","",m.group(1))]
    gates=[Gate("GATE-0","PASS" if tu_ok else "FAIL","TU2 applied 0.0.0.1 -> 0.0.2.1" if tu_ok else "expected TU2 application was not proven",[f"{a} -> {b}" for a,b in tus[-5:]] or ["no XEX patch-success line"])]
    progress=bool(vds or swaps)
    if not progress: g2s="INCONCLUSIVE"; g2m=f"{total} unresolved dispatch(es); no renderer progress evidence" if total else "zero unresolved seen, but no renderer progress evidence"
    elif total: g2s="FAIL"; g2m=f"{total} unresolved guest dispatch(es), {len(unresolved)} unique target(s)"
    else: g2s="PASS"; g2m="zero unresolved guest dispatches with renderer progress evidence"
    ev=[f"0x{a:08X}: {c} call(s)" for a,c in unresolved.most_common()] or ["no unresolved-dispatch lines found"]
    if regs: ev.append(f"reported registered functions: {max(regs)}")
    gates.append(Gate("GATE-2",g2s,g2m,ev))
    if g2s!="PASS": gates.append(Gate("GATE-3","BLOCKED","framebuffer gate blocked until GATE-2 passes",[f"SwapGuest samples={len(swaps)}; non-zero={len(nonzero)}"]))
    elif nonzero:
        best=max(nonzero,key=lambda s:s["nonzero"]); gates.append(Gate("GATE-3","PASS",f"guest framebuffer became non-zero ({best['nonzero']} sampled bytes)",[f"{best['ptr']} {best['hash']}"]))
    elif swaps: gates.append(Gate("GATE-3","FAIL",f"all {len(swaps)} sampled guest framebuffers remained zero",[]))
    else: gates.append(Gate("GATE-3","INCONCLUSIVE","GATE-2 passed but no SwapGuest sample was logged",[]))
    for gid,label in [("GATE-4","intro/menu"),("GATE-5","input/menu navigation"),("GATE-6","New Game"),("GATE-7","first gameplay"),("GATE-8","audio/video sync"),("GATE-9","checkpoint/save/load"),("GATE-10","languages"),("GATE-11","campaign complete"),("GATE-12","TU2/DLC"),("GATE-13","PC modernization")]:
        gates.append(Gate(gid,"UNVERIFIED",f"{label} requires later explicit evidence",[]))
    diagnosis=[]
    if total: diagnosis.append("PRIMARY: guest function coverage/dispatch. Do not attribute the black frame to VFETCH-OOB while GATE-2 is failing.")
    elif progress and swaps and not nonzero: diagnosis.append("PRIMARY NEXT: guest framebuffer is still zero after dispatch coverage passed; renderer/shader/resolve investigation is unlocked.")
    elif nonzero: diagnosis.append("Framebuffer production is alive; any visual failure is downstream of guest framebuffer generation.")
    else: diagnosis.append("Insufficient runtime progress evidence for subsystem attribution.")
    vf=len(VFETCH_RE.findall(data))
    if vf: diagnosis.append(f"SECONDARY: {vf} VFETCH-OOB warning(s); preserve as diagnostics until GATE-2 is PASS.")
    if not FIBER_RE.search(data): diagnosis.append("TU2 fiber callback-clear marker not observed; fiber status is unproven for this RUN.")
    av=len(ACCESS_RE.findall(data))
    if av: diagnosis.append(f"Access-violation diagnostics observed: {av}.")
    return {"schema":1,"audit":"dantes-inferno-runtime-gates","metrics":{"registered_functions":max(regs) if regs else None,"unresolved_dispatch_total":total,"unresolved_unique_targets":len(unresolved),"unresolved_targets":{f"0x{a:08X}":c for a,c in unresolved.most_common()},"fiber_callback_cleared":bool(FIBER_RE.search(data)),"vdswap_count":len(vds),"vdswap_sizes":sorted({f"{a}x{b}" for a,b in vds}),"swapguest_samples":len(swaps),"swapguest_nonzero_samples":len(nonzero),"vfetch_oob_count":vf,"access_violation_marker_count":av},"gates":[asdict(g) for g in gates],"diagnosis":diagnosis}

def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument("log"); ap.add_argument("--json",dest="json_path"); ap.add_argument("--markdown",dest="md_path"); a=ap.parse_args()
    p=Path(a.log)
    if not p.exists(): print(f"ERROR: log not found: {p}"); return 2
    r=report(p.read_text(encoding="utf-8",errors="replace"))
    for g in r["gates"]:
        print(f"[{g['status']:12}] {g['id']:8} {g['summary']}")
        for e in g["evidence"]: print(f"               - {e}")
    for d in r["diagnosis"]: print("DIAG:",d)
    if a.json_path:
        q=Path(a.json_path); q.parent.mkdir(parents=True,exist_ok=True); q.write_text(json.dumps(r,indent=2)+"\n",encoding="utf-8")
    if a.md_path:
        q=Path(a.md_path); q.parent.mkdir(parents=True,exist_ok=True); lines=["# Dante's Inferno RUN Gate Report","","| Gate | Status | Evidence summary |","|---|---|---|"]+[f"| `{g['id']}` | **{g['status']}** | {g['summary']} |" for g in r["gates"]]+["","## Diagnosis",""]+[f"- {d}" for d in r["diagnosis"]]; q.write_text("\n".join(lines)+"\n",encoding="utf-8")
    return 1 if any(g["id"] in {"GATE-0","GATE-2"} and g["status"]=="FAIL" for g in r["gates"]) else 0
if __name__=="__main__": raise SystemExit(main())
