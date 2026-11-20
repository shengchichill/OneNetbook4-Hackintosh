// vashim: shim for /Library/GPUBundles/AppleIntelTGLGraphicsVADriver.bundle (route ③).
// Step 1: log every slot (now only in trace mode, see g_trace). Step 2: pixel transfers (fn 0x3ea) done on the CPU.
//
// AppleGVA/AppleGVACore load <bundle>/Contents/MacOS/AppleIntelTGLGraphicsVADriver and call
//   int AVD_CreateAVDAccelerator(void **outTable, const void *params /*0x28 bytes*/, uint32_t *outVersion)
//   int AVD_DestroyAVDAccelerator(void *table)
// The table is 0x90 bytes: [0] = driver-internal state, [1..16] = function pointers (slot offsets 0x08..0x80;
// 0x58 = ScheduleAVDCommands). This shim takes the executable's name, dlopen()s the real driver renamed to
// AppleIntelTGLGraphicsVADriver.real (same directory, so its @loader_path/TGLVA still resolves), calls its Create,
// copies the table and swaps every slot for a wrapper that forwards unchanged (logging arguments in trace mode);
// slot 0x58/0x60: pixel-transfer batches (fn 0x3ea) never reach the real driver; known ones are done with vImage
// (swconvert.c), see "Step 2" below.
//
// All slot functions take ≤3 pointer/int register args and return int (checked in the disassembly: no stack or
// xmm arguments), so a 6-register passthrough is safe.
//
// Log: /usr/bin/log stream --level debug --predicate 'subsystem == "org.onb4.vashim"'
// Build: see build.sh next to this file.
#include <dlfcn.h>
#include <libgen.h>
#include <limits.h>
#include <mach/mach.h>
#include <mach-o/dyld.h>
#include <os/log.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <CoreFoundation/CoreFoundation.h>
#include <IOSurface/IOSurface.h>
#include "swconvert.h"

#define NSLOTS 16 /* table slots 1..16 (offsets 0x08..0x80) */
#define TABLE_SIZE 0x90
#define DUMP 64

typedef uint64_t (*fn6)(uint64_t, uint64_t, uint64_t, uint64_t, uint64_t, uint64_t);
typedef int (*create_fn)(void **, const void *, uint32_t *);
typedef int (*destroy_fn)(void *);

static os_log_t g_log;
static void *g_real;           // dlopen handle
static uintptr_t g_real_base;  // mach header of the real driver (for printing image-relative addresses)
static create_fn g_create;
static destroy_fn g_destroy;
static _Atomic(fn6) g_slot[NSLOTS + 1];
static _Atomic uint64_t g_seq;

// Read memory without faulting on bad pointers.
static int safe_read(uint64_t addr, void *buf, size_t len) {
    if (addr < 0x1000) return 0;
    vm_size_t got = 0;
    kern_return_t kr = vm_read_overwrite(mach_task_self(), (vm_address_t)addr, len, (vm_address_t)buf, &got);
    return kr == KERN_SUCCESS && got == len;
}

static void hex(const uint8_t *p, size_t n, char *out) {
    static const char d[] = "0123456789abcdef";
    for (size_t i = 0; i < n; i++) {
        *out++ = d[p[i] >> 4];
        *out++ = d[p[i] & 15];
        if ((i & 7) == 7 && i + 1 < n) *out++ = ' ';
    }
    *out = 0;
}

// "<what>@ptr: 16 qwords hex" or "<what>@ptr: (unreadable)"
static void dump(uint64_t seq, const char *what, uint64_t ptr, size_t n) {
    uint8_t buf[256];
    char txt[256 * 2 + 40];
    if (n > sizeof buf) n = sizeof buf;
    if (!ptr) return;
    if (!safe_read(ptr, buf, n)) {
        os_log(g_log, "#%llu   %{public}s@%#llx: (unreadable)", seq, what, ptr);
        return;
    }
    hex(buf, n, txt);
    os_log(g_log, "#%llu   %{public}s@%#llx: %{public}s", seq, what, ptr, txt);
}

static uint64_t rel(uint64_t p) {  // image-relative if inside the real driver's __TEXT/__DATA range (rough: < 16 MB)
    return (g_real_base && p >= g_real_base && p - g_real_base < 0x1000000) ? p - g_real_base : 0;
}

// slot 0x58: ScheduleAVDCommands(ctx, {u32 n; cmd **v}, {?, out *v})
// cmd: +0 u32, +8 u64, +0x10 u32 (function), +0x18 handler object (C++ vtable), +0x30 buddy cmd
static void describe_schedule(uint64_t seq, uint64_t cmds, uint64_t outs) {
    struct { uint32_t n, pad; uint64_t v; } hdr;
    if (!safe_read(cmds, &hdr, sizeof hdr)) return;
    os_log(g_log, "#%llu   schedule: n=%u v=%#llx", seq, hdr.n, hdr.v);
    for (uint32_t i = 0; i < hdr.n && i < 8; i++) {
        uint64_t c;
        if (!safe_read(hdr.v + 8ull * i, &c, 8)) break;
        for (int depth = 0; c && depth < 4; depth++) {  // follow buddy chain
            uint8_t cb[0x40];
            if (!safe_read(c, cb, sizeof cb)) break;
            uint64_t handler = *(uint64_t *)(cb + 0x18), vt = 0, buddy = *(uint64_t *)(cb + 0x30);
            safe_read(handler, &vt, 8);
            char txt[0x40 * 2 + 16];
            hex(cb, sizeof cb, txt);
            os_log(g_log, "#%llu   cmd[%u.%d]@%#llx type=%u fn=%#x handler=%#llx vtable=%#llx(rel %#llx): %{public}s",
                   seq, i, depth, c, *(uint32_t *)cb, *(uint32_t *)(cb + 0x10), handler, vt, rel(vt), txt);
            dump(seq, "  handler", handler, 0x80);
            c = buddy;
        }
    }
    struct { uint64_t a, v; } o;
    if (safe_read(outs, &o, sizeof o)) os_log(g_log, "#%llu   outs: %#llx %#llx", seq, o.a, o.v);
}

// Trace mode (per-slot argument dumps, Step 1 behaviour): /var/tmp/vashim-trace exists or VASHIM_TRACE is set
// when the process creates its first accelerator. VASHIM_DEEP=1 additionally follows pointers two levels
// (in-process callers such as vtxfer only).
static int g_trace, g_deep;
static void deep(uint64_t seq, const char *path, uint64_t ptr, size_t n, int depth) {
    uint64_t q[32];
    if (n > sizeof q) n = sizeof q;
    if (!safe_read(ptr, q, n)) return;
    dump(seq, path, ptr, n);
    if (depth <= 0) return;
    for (size_t i = 0; i < n / 8; i++) {
        uint64_t v = q[i];
        if (v < 0x100000000ull || v > 0x7fffffffffffull || (v & 7) || rel(v)) continue;  // heap/stack only, skip driver image
        char sub[96];
        snprintf(sub, sizeof sub, "%s+%#zx", path, i * 8);
        deep(seq, sub, v, 0x80, depth - 1);
    }
}

// ---- Step 2: CPU pixel transfer -------------------------------------------------------------------------------
// A conversion command is type 2 / fn 0x3ea (decode is fn 0x3e9). Two handler classes were seen:
//  - VHAL_VideoProcessor (vtable rel 0x75d018; VTPixelTransfer from apps): the real driver rejects these (err 11).
//    The main command's +0x20 points to { IOSurfaceRef src; double srcRect[4]; IOSurfaceRef dst; double dstRect[4]; }
//  - AVD_VideoProcessingContext (seen in VTDecoderXPCService during Music HEVC playback): the real driver SUBMITS
//    Apple's media kernel and the GPU hangs (RCS, 2026-11-06 14:05) -> whole machine freezes.
// So fn 0x3ea batches never reach the real driver: known descriptors are done on the CPU, anything else is
// logged and skipped (output left as is). The matching completion query (slot 0x60) is answered here too.
#define VT_VHAL_VIDEOPROCESSOR 0x75d018
typedef struct { uint64_t src; double sr[4]; uint64_t dst; double dr[4]; } xfer_desc;
static _Atomic int g_xfer_ok, g_xfer_fail, g_xfer_skip;

static int is_surface(uint64_t p) {
    uint64_t probe[2];
    if (!safe_read(p, probe, sizeof probe)) return 0;
    return CFGetTypeID((CFTypeRef)p) == IOSurfaceGetTypeID();
}

// Classify a schedule batch (following buddy chains): returns 1 if every command is fn 0x3ea, 0 if none is,
// -1 if mixed or unreadable. *unsafe is set when any fn 0x3ea command uses a handler other than VHAL_VideoProcessor
// (those are the ones the real driver actually submits to the GPU).
static int batch_is_xfer(uint64_t cmds, int *unsafe) {
    struct { uint32_t n, pad; uint64_t v; } hdr;
    *unsafe = 0;
    if (!safe_read(cmds, &hdr, sizeof hdr) || hdr.n == 0 || hdr.n > 64) return -1;
    int x = 0, other = 0;
    for (uint32_t i = 0; i < hdr.n; i++) {
        uint64_t c;
        if (!safe_read(hdr.v + 8ull * i, &c, 8)) return -1;
        for (int depth = 0; c && depth < 8; depth++) {
            uint8_t cb[0x38];
            uint64_t vt = 0;
            if (!safe_read(c, cb, sizeof cb)) return -1;
            if (*(uint32_t *)(cb + 0x10) == 0x3ea) {
                x++;
                safe_read(*(uint64_t *)(cb + 0x18), &vt, 8);
                if (rel(vt) != VT_VHAL_VIDEOPROCESSOR) *unsafe = 1;
            } else other++;
            c = *(uint64_t *)(cb + 0x30);
        }
    }
    return other ? (x ? -1 : 0) : 1;
}

static void sw_transfer(uint64_t seq, uint64_t cmds) {
    struct { uint32_t n, pad; uint64_t v; } hdr;
    if (!safe_read(cmds, &hdr, sizeof hdr)) return;
    for (uint32_t i = 0; i < hdr.n; i++) {
        uint64_t c, vt = 0;
        uint8_t cb[0x40];
        if (!safe_read(hdr.v + 8ull * i, &c, 8) || !safe_read(c, cb, sizeof cb)) continue;
        uint32_t type = *(uint32_t *)cb;
        uint64_t handler = *(uint64_t *)(cb + 0x18), descp = *(uint64_t *)(cb + 0x20);
        safe_read(handler, &vt, 8);
        if (rel(vt) != VT_VHAL_VIDEOPROCESSOR || type != 2 || !descp) {
            int n = atomic_fetch_add(&g_xfer_skip, 1);
            if (n < 3 || g_trace) {
                os_log(g_log, "#%llu xfer SKIPPED (not sent to GPU): type=%u handler vtable rel %#llx", seq, type, rel(vt));
                dump(seq, "cmd", c, 0x40);
                dump(seq, "cmd+0x20", descp, 0x100);
            }
            continue;
        }
        xfer_desc dsc = {0};
        char why[96] = "bad descriptor";
        int ok = safe_read(descp, &dsc, sizeof dsc) && is_surface(dsc.src) && is_surface(dsc.dst) &&
                 vashim_convert((IOSurfaceRef)dsc.src, dsc.sr, (IOSurfaceRef)dsc.dst, dsc.dr, why, sizeof why) == 0;
        int nok = ok ? atomic_fetch_add(&g_xfer_ok, 1) : atomic_fetch_add(&g_xfer_fail, 1);
        if (nok < 5 || g_trace)  // first few of each per process, everything in trace mode
            os_log(g_log, "#%llu xfer %{public}s: %{public}s src %#llx (%g,%g %gx%g) -> dst %#llx (%g,%g %gx%g)",
                   seq, ok ? "ok" : "FAILED", why, dsc.src, dsc.sr[0], dsc.sr[1], dsc.sr[2], dsc.sr[3],
                   dsc.dst, dsc.dr[0], dsc.dr[1], dsc.dr[2], dsc.dr[3]);
        if (!ok && nok < 3) dump(seq, "desc", descp, 0x60);
    }
}

// slot 0x60: b = {u32 n; entry *v}, entry (0x18 bytes) = {void *req; u32 fn; u32 flag; u32 status}; status 1 = done.
// Returns 1 if every entry was fn 0x3ea and has been answered here.
static int answer_xfer_query(uint64_t q) {
    struct { uint32_t n, pad; uint64_t v; } hdr;
    if (!safe_read(q, &hdr, sizeof hdr) || hdr.n == 0 || hdr.n > 64) return 0;
    for (uint32_t i = 0; i < hdr.n; i++) {
        struct { uint64_t req; uint32_t fn, flag, status; } e;
        if (!safe_read(hdr.v + 0x18ull * i, &e, 0x14) || e.fn != 0x3ea) return 0;
    }
    for (uint32_t i = 0; i < hdr.n; i++) {
        uint8_t *e = (uint8_t *)(hdr.v + 0x18ull * i);
        if (*(uint64_t *)e) *(uint32_t *)(e + 0x10) = 1;
    }
    return 1;
}

static uint64_t call_slot(int s, uint64_t a, uint64_t b, uint64_t c, uint64_t d, uint64_t e, uint64_t f) {
    fn6 real = atomic_load(&g_slot[s]);
    uint64_t seq = atomic_fetch_add(&g_seq, 1);
    if (g_trace) {
        os_log(g_log, "#%llu > slot %#x(%#llx, %#llx, %#llx, %#llx)", seq, s * 8, a, b, c, d);
        dump(seq, "a", a, DUMP);
        dump(seq, "b", b, DUMP);
        dump(seq, "c", c, DUMP);
        if (s * 8 == 0x58) describe_schedule(seq, b, c);
        if (g_deep) { deep(seq, "B", b, 0x80, 2); deep(seq, "C", c, 0x80, 2); }
    }
    uint64_t r;
    if (s * 8 == 0x58 && a && b) {
        int unsafe, x = batch_is_xfer(b, &unsafe);
        if (x == 1) { sw_transfer(seq, b); r = 0; }  // never forwarded: see the comment above
        else if (x < 0 && unsafe) {                  // mixed batch with a GPU-submitting transfer: drop it all
            os_log_error(g_log, "#%llu schedule: mixed batch with non-VHAL transfer, NOT forwarded (returns 1)", seq);
            dump(seq, "batch", b, 0x20);
            r = 1;
        } else {
            if (x < 0) os_log_error(g_log, "#%llu schedule: mixed or unreadable batch, forwarded", seq);
            r = real(a, b, c, d, e, f);
        }
    } else if (s * 8 == 0x60 && a && b && answer_xfer_query(b)) {
        r = 0;
    } else {
        r = real(a, b, c, d, e, f);
    }
    if (g_trace) {
        os_log(g_log, "#%llu < slot %#x = %#llx", seq, s * 8, r);
        if (s == 1) { uint64_t out = 0; if (safe_read(a, &out, 8)) os_log(g_log, "#%llu   *a = %#llx", seq, out); }
        dump(seq, "b'", b, DUMP);  // outputs written into the arg struct
        dump(seq, "c'", c, DUMP);
    }
    return r;
}

#define W(n) static uint64_t w##n(uint64_t a, uint64_t b, uint64_t c, uint64_t d, uint64_t e, uint64_t f) { \
    return call_slot(n, a, b, c, d, e, f); }
W(1) W(2) W(3) W(4) W(5) W(6) W(7) W(8) W(9) W(10) W(11) W(12) W(13) W(14) W(15) W(16)
static fn6 const g_wrap[NSLOTS + 1] = {0, w1, w2, w3, w4, w5, w6, w7, w8, w9, w10, w11, w12, w13, w14, w15, w16};

static int load_real(void) {
    if (g_real) return 1;
    Dl_info di;
    if (!dladdr((void *)load_real, &di) || !di.dli_fname) return 0;
    char dir[PATH_MAX], path[PATH_MAX];
    strlcpy(dir, di.dli_fname, sizeof dir);
    snprintf(path, sizeof path, "%s/AppleIntelTGLGraphicsVADriver.real", dirname(dir));
    void *h = dlopen(path, RTLD_NOW | RTLD_LOCAL);
    if (!h) { os_log_error(g_log, "dlopen %{public}s: %{public}s", path, dlerror()); return 0; }
    g_create = (create_fn)dlsym(h, "AVD_CreateAVDAccelerator");
    g_destroy = (destroy_fn)dlsym(h, "AVD_DestroyAVDAccelerator");
    if (!g_create || !g_destroy) { os_log_error(g_log, "dlsym failed"); return 0; }
    if (dladdr((void *)g_create, &di)) g_real_base = (uintptr_t)di.dli_fbase;
    g_real = h;
    os_log(g_log, "loaded %{public}s base=%#lx", path, g_real_base);
    return 1;
}

__attribute__((visibility("default")))
int AVD_CreateAVDAccelerator(void **outTable, const void *params, uint32_t *outVersion) {
    if (!g_log) {
        g_log = os_log_create("org.onb4.vashim", "slot");
        g_trace = getenv("VASHIM_TRACE") || access("/var/tmp/vashim-trace", F_OK) == 0;
        g_deep = getenv("VASHIM_DEEP") != NULL;
        if (g_deep) g_trace = 1;
    }
    if (!load_real()) return 7;
    uint64_t seq = atomic_fetch_add(&g_seq, 1);
    os_log(g_log, "#%llu > Create(%p, %p, %p) pid=%d %{public}s", seq, outTable, params, outVersion, getpid(), getprogname());
    if (g_trace) dump(seq, "params", (uint64_t)params, 0x28);
    int r = g_create(outTable, params, outVersion);
    void *real = outTable ? *outTable : NULL;
    os_log(g_log, "#%llu < Create = %d table=%p version=%#x", seq, r, real, outVersion ? *outVersion : 0);
    if (r || !real) return r;
    if (g_trace) {
        dump(seq, "table", (uint64_t)real, TABLE_SIZE);
        dump(seq, "state", ((uint64_t *)real)[0], 0x38);
    }

    // [0..0x90) copy of the real table with wrapped slots, [0x90] = pointer to the real table (for Destroy)
    uint64_t *mine = calloc(1, TABLE_SIZE + 8);
    if (!mine) return r;  // fall back to the unwrapped table
    memcpy(mine, real, TABLE_SIZE);
    for (int s = 1; s <= NSLOTS; s++) {
        fn6 f = (fn6)((uint64_t *)real)[s], prev = atomic_load(&g_slot[s]);
        if (prev && prev != f) os_log_error(g_log, "slot %#x changed %p -> %p", s * 8, prev, f);
        atomic_store(&g_slot[s], f);
        if (f) mine[s] = (uint64_t)g_wrap[s];
        if (g_trace) os_log(g_log, "#%llu   slot %#x = %p (rel %#llx)", seq, s * 8, f, rel((uint64_t)f));
    }
    mine[TABLE_SIZE / 8] = (uint64_t)real;
    *outTable = mine;
    return r;
}

__attribute__((visibility("default")))
int AVD_DestroyAVDAccelerator(void *table) {
    if (!g_destroy || !table) return 5;
    uint64_t *mine = table, *real = (uint64_t *)mine[TABLE_SIZE / 8];
    os_log(g_log, "Destroy(%p) real=%p xfer ok %d failed %d skipped %d", table, real,
           atomic_load(&g_xfer_ok), atomic_load(&g_xfer_fail), atomic_load(&g_xfer_skip));
    int r = g_destroy(real);
    free(mine);
    return r;
}
