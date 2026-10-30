"""Compares two RPCS3 PPU profiler results for one PPU thread (default main_thread) and lists the functions that gained
the most samples, e.g. a host run with 16 fake clients against one without.

Recording: set `PPU Profiler: true` in the RPCS3 custom config (back it up first), run the host, then close its window
(CloseMainWindow, not kill): RPCS3 writes the results to log/RPCS3.log only when emulation stops. Copy the log before
the next start. The profiler lists only the top functions of each thread and counts samples where the thread waits in
a syscall as "idle".

    python tools/ppu_profile.py base.log with.log [thread] [rows]

Names come from research/ghidra/natives.json (UE3 exec functions); 0x1ec0000-0x20f0000 is PRX/HLE code.
"""
import json, re, sys

natives = json.load(open(r"D:/dust514srv/research/ghidra/natives.json"))
code2name = {int(v["code"], 16): k for k, v in natives.items()}
HEAD = re.compile(r'Thread "([^"]+)" \[0x[0-9a-f]+\]: (\d+) samples \(([\d.]+)% idle\), (\d+) new')
ROW = re.compile(r"^\s*\[0x([0-9a-f]+)\]: [\d.]+% \((\d+)\)")


def parse(path, thread):
    rows, head, inside = {}, None, False
    for line in open(path, encoding="utf-8", errors="replace"):
        m = HEAD.search(line)
        if m:
            inside = thread in m[1]
            if inside:
                head = (int(m[2]), float(m[3]), int(m[4]))
            continue
        if inside:
            r = ROW.match(line)
            if r:
                rows[int(r[1], 16)] = int(r[2])
            elif line.strip() and not line.startswith("\t"):
                inside = False
    return head, rows


def name(a):
    if a in code2name:
        return code2name[a]
    if 0x1EC0000 <= a < 0x20F0000:
        return "(PRX/HLE)"
    return ""


thread = sys.argv[3] if len(sys.argv) > 3 else "main_thread"
n = int(sys.argv[4]) if len(sys.argv) > 4 else 40
(h0, r0), (h1, r1) = parse(sys.argv[1], thread), parse(sys.argv[2], thread)
for label, h in (("base", h0), ("with", h1)):
    total, idle, busy = h
    print("%s: %d samples, %.1f %% idle, %d busy, listed %d" % (label, total, idle, busy, sum((r0, r1)[label == "with"].values())))
diff = {a: r1.get(a, 0) - r0.get(a, 0) for a in set(r0) | set(r1)}
gain = sum(v for v in diff.values() if v > 0)
print("busy delta %d (listed delta %d)" % (h1[2] - h0[2], sum(diff.values())))
for a, d in sorted(diff.items(), key=lambda kv: -kv[1])[:n]:
    print("  %#09x  %+6d  %5.1f %%  base %6d  with %6d  %s" % (a, d, 100.0 * d / gain, r0.get(a, 0), r1.get(a, 0), name(a)))
