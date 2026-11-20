#!/usr/bin/env python3
"""解析 WEX ㉕／㉖ 的 ONB4SchedTrace（Apple 排程器事件環 + hang 凍結快照）。
用法：
  ssh user@<IP> 'ioreg -p IOService -d 1 -l -w0' > x.txt
  python3 tools/onb4-sched.py x.txt [-n 顯示最後幾筆，預設 120] [--all]
㉖（格式 v2）：連續 1024 筆沒有 submit 就進「安靜模式」，主環停寫（保留 hang 起點），之後的事件寫 256 筆小環＋按種類計數。
沒凍結時 WEX 只輸出最後 64 筆（確認 hook 有在跑）；hang 偵測（TGLHangPreStop）後凍結 4096 筆 + 快照。
看點：最後一次 submit(10) 之後，CSB(11) 有沒有回來、之後 schedDispatch(2) 有沒有被呼叫、
      有沒有走到 dequeue(4)、evalWait/evalWork 回傳是否帶 0x8、有沒有 prepSubmit(8)；
      快照裡 work queue 的 派(0x4040) != 寫(0x4048)（有工作沒派）、wait queue（0x3c0）擋住誰、0x1c3c/0x1c00/0x1c38。
"""
import re
import struct
import sys

KIND = {1: "SWI", 2: "dispatch", 3: "dispatch-ret", 4: "dequeue", 5: "dequeue-ret", 6: "evalWait",
        7: "evalWork", 8: "prepSubmit", 9: "moveWait", 10: "submit", 11: "CSB", 12: "【安靜】"}
CSBH = {0: "IdleToActive", 1: "Preempted/NewQueue", 2: "ElementSwitch", 3: "ActiveToIdle"}
BAD = 0xdeadbeefdeadbeef


def st_str(st):
    el = (st >> 12) & 0xf
    return (f"c3c={st & 1} c00={(st >> 1) & 1} pre={(st >> 2) & 3:x} c38={(st >> 4) & 0xf} bank={(st >> 8) & 0xf} "
            f"el={el:04b} dpsmIdle={(st >> 16) & 1} f1190={st >> 24:02x}")


def q_str(qa, qb):
    if qa == 0xffffffff:
        return "q=?"
    q, rd, ds, wr = qa & 0xff, (qa >> 8) & 0x1ff, (qa >> 20) & 0x1ff, qb & 0x1ff
    mark = "  ← 有未派" if ds != wr else ""
    return f"q{q} 讀{rd:03x} 派{ds:03x} 寫{wr:03x}{mark}"


def detail(k, a, b, ret):
    if k == 1:
        return f"source={'有' if a else '無'} count={b}"
    if k in (2, 3, 4, 5):
        return f"flags={a:#x}"
    if k == 6:
        return f"x={a & 1} y={(a >> 1) & 1} throttled={(a >> 2) & 1} → ret={ret:#x}{' (有可送)' if ret & 8 else ''}"
    if k == 7:
        return f"{'R ' if a >> 31 else ''}flags={a & 0x7fffffff:#x} out=[{b & 0xffff},{b >> 16}] → ret={ret:#x}{' (有可送)' if ret & 8 else ''}"
    if k == 8:
        return f"flags={a:#x} eval={b:#x} cnt=[{ret & 0xffff},{ret >> 16}]"
    if k == 9:
        return f"port={a & 0xff} q={(a >> 8) & 0xff} x={(a >> 16) & 1} y={(a >> 17) & 1} itemFlags={b:#x} tail={ret:#x}"
    if k == 10:
        return f"ordinal={a} flags={b:#x}"
    if k == 12:
        return (f"開始：連續 {b} 筆沒有 submit，之後只寫小環＋計數" if a == 0
                else f"結束：略過 {b} 筆、持續 {ret} ms（下一筆是 submit）")
    if k == 11:
        return f"{CSBH.get(a & 0xff, a & 0xff)} idx={a >> 8} raw={ret:08x}_{b:08x}"
    return f"a={a:#x} b={b:#x} ret={ret:#x}"


def show(path, last, show_all):
    text = open(path, errors="replace").read()
    m = re.search(r'"ONB4SchedTrace" = <([0-9a-fA-F]*)>', text)
    if not m:
        print(f"{path}: 找不到 ONB4SchedTrace（WEX ㉕ 沒載入？）")
        r = re.search(r'"ONB4SchedRouted" = (\d+)', text)
        if r:
            print(f"  ONB4SchedRouted={r.group(1)}")
        return
    raw = bytes.fromhex(m.group(1))
    ver, frozen, pos, count, ring_n, routes, flo, fhi = struct.unpack_from("<8I", raw)
    fns = flo | fhi << 32
    snap = 4096 if frozen else 0
    tail = []
    if ver >= 2:
        quiet, tpos, tcount, supp, supp_total, episodes, qlo, qhi = struct.unpack_from("<8I", raw, 32)
        kinds = struct.unpack_from("<16I", raw, 64)
        base = 128
        nev = count
        toff = base + count * 64
        for i in range(tcount):
            e = struct.unpack_from("<IIQIIIIQQIIII", raw, toff + i * 64)
            if e[0]:
                tail.append((e[0], e[1] & 0xff) + e[2:])
        tail.sort()
    else:
        base = 32
        nev = (len(raw) - 32 - snap) // 64
    print(f"== {path}  ver={ver} routes={routes} {'【已凍結】' if frozen else '（未凍結，只輸出最後 64 筆）'} 總事件={pos} 本次輸出={nev}")
    if ver >= 2:
        qns = qlo | qhi << 32
        kc = {KIND.get(i, i): c for i, c in enumerate(kinds) if c}
        print(f"  安靜模式：{'進行中' if quiet else '否'}  次數={episodes}  累計略過={supp_total}  本次略過={supp} 小環={tpos}（輸出 {tcount}）"
              + (f"  種類={kc}" if episodes else ""))
    evs = []
    for i in range(nev):
        seq, kind, ns, a, b, ret, st, m240, m3c0, rr, csb, qa, qb = struct.unpack_from("<IIQIIIIQQIIII", raw, base + i * 64)
        if seq == 0:
            continue
        evs.append((seq, kind & 0xff, ns, a, b, ret, st, m240, m3c0, rr, csb, qa, qb))
    evs.sort()
    if not evs:
        print("  （沒有事件）")
        return
    ref = fns if frozen and fns else max(evs[-1][2], tail[-1][2] if tail else 0)
    if ver >= 2 and episodes:
        print(f"  最近一次安靜期開始於參考點前 {(ref - qns) / 1e6:.1f} ms")
    last_sub = max((e[0] for e in evs if e[1] == 10), default=None)
    if last_sub is not None:
        after = [e for e in evs if e[0] > last_sub]
        cnt = {}
        for e in after:
            cnt[KIND.get(e[1], e[1])] = cnt.get(KIND.get(e[1], e[1]), 0) + 1
        sub = next(e for e in evs if e[0] == last_sub)
        print(f"  最後一次 submit：seq {last_sub} ordinal={sub[3]}，在參考點前 {(ref - sub[2]) / 1e6:.1f} ms；之後事件：{cnt or '無'}")
    shown = evs if show_all else evs[-last:]
    print("    seq     t(ms)   事件          細節                                              狀態 / m240 m3c0 rr / queue")
    prev = None
    for seq, k, ns, a, b, ret, st, m240, m3c0, rr, csb, qa, qb in shown:
        line = (f"  {seq:7d} {(ns - ref) / 1e6:9.2f}  {KIND.get(k, k):12s}  {detail(k, a, b, ret):48s}  ")
        state = f"{st_str(st)} m240={m240:x} m3c0={m3c0:x} rr={rr & 0xffff}/{rr >> 16} csb={csb} {q_str(qa, qb)}"
        print(line + (state if state != prev else "〃"))
        prev = state
    if tail:
        print(f"\n  == 安靜期小環（最後 {len(tail)} 筆；seq 是小環內序號）==")
        prev = None
        for seq, k, ns, a, b, ret, st, m240, m3c0, rr, csb, qa, qb in (tail if show_all else tail[-last:]):
            line = (f"  t{seq:6d} {(ns - ref) / 1e6:9.2f}  {KIND.get(k, k):12s}  {detail(k, a, b, ret):48s}  ")
            state = f"{st_str(st)} m240={m240:x} m3c0={m3c0:x} rr={rr & 0xffff}/{rr >> 16} csb={csb} {q_str(qa, qb)}"
            print(line + (state if state != prev else "〃"))
            prev = state
    if not frozen:
        return
    s = struct.unpack_from("<512Q", raw, len(raw) - 4096)
    print("\n  == 凍結快照 ==")
    if not s[2]:
        print("  （沒有 RCS streamer 指標，快照空白）")
        return
    print(f"  cs={s[2]:#x} sched={s[15]:#x}  bank={s[7]}  el(0x30,0x38,0x40,0x48)={[hex(x) for x in s[3:7]]}")
    print(f"  m240(有工作)={s[8]:#x}  m3c0(wait)={s[9]:#x}  rr380={s[10] & 0xffffffff} rr384={s[10] >> 32}")
    f = s[11]
    print(f"  c1c00(pause)={f & 0xff} c1c3c(可送)={(f >> 8) & 0xff} c1c50={(f >> 16) & 0xff} c1c5d={(f >> 24) & 0xff} csbIdx={f >> 32}"
          f"  c1c38(SWI guard)={s[12]:#x}  acc1458={s[13]:#x} acc1190={s[14]:#x}")
    for i in range(4):
        it = s[16 + i * 4:20 + i * 4]
        if s[3 + i] and s[3 + i] != BAD:
            print(f"  el槽{i}: item={s[3 + i]:#x} ctx={it[0]:#x} +8={it[1]:#x} +0x10={it[2]:#x} +0x18={it[3]:#x} (flags={it[3] >> 32:#x})")
    for k in range(8):
        w = s[32 + k * 8:40 + k * 8]
        if not any(w[1:]):
            continue
        print(f"  wait q{w[0]}:" + "".join(
            f"  port{p}: item={w[1 + p * 3]:#x} stamp(idx|flags)={w[2 + p * 3] & 0xffffffff:#x} 值={w[2 + p * 3] >> 32:#x}"
            f" itemFlags={w[3 + p * 3] & 0xffffffff:#x} tail={w[3 + p * 3] >> 32:#x}" for p in range(2)))
    print("  work queues（非空槽）：")
    for k in range(24):
        w = s[96 + k * 16:112 + k * 16]
        if not w[1]:
            continue
        rd, ds, wr = w[2], w[3], w[4]
        flag = "  ← 有未派工作" if wr != ds else ("  （有未回收）" if rd != ds else "")
        print(f"    q{w[0]:2d} @{w[1]:#x} 讀={rd:#x} 派={ds:#x} 寫={wr:#x}{flag}")
        if rd != wr or show_all:
            n = min(5, (wr - rd) & 0x1ff) or (5 if show_all else 0)
            for i in range(n):
                ctx, x = w[5 + i * 2], w[6 + i * 2]
                print(f"        [{(rd + i) & 0x1ff:03x}] ctx={ctx:#x} tail={x & 0xffffffff:#x} flags={x >> 32:#x}")


def main():
    args = sys.argv[1:]
    last, show_all = 120, False
    if "--all" in args:
        show_all = True
        args.remove("--all")
    if "-n" in args:
        i = args.index("-n")
        last = int(args[i + 1])
        del args[i:i + 2]
    if not args:
        print(__doc__)
        sys.exit(1)
    for p in args:
        show(p, last, show_all)


if __name__ == "__main__":
    main()
