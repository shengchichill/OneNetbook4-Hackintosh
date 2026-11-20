// vtxfer: exercise VTPixelTransferSession (the path WebKit's drawVideoFrame uses:
//   ImageTransferSessionVT::convertPixelBuffer -> VTPixelTransferSessionTransferImage -> AppleGVA -> GPU VA driver).
// Each case runs in a forked child so a crash in one case is reported (signal) and the rest still run.
// Usage: vtxfer [iterations=60] [case-filter-substring]   (run with an absolute path: it re-spawns itself per case)
// The destination is pre-filled with 0x5A; after the transfers it reports how much of it was written ("wrote N%")
// and a checksum, so a driver that returns success without doing the work shows up as "wrote 0%".
// Build: clang -arch x86_64 -mmacosx-version-min=26.0 -fobjc-arc -framework Foundation -framework VideoToolbox \
//        -framework CoreMedia -framework CoreVideo -framework IOSurface -o vtxfer vtxfer.m
#import <Foundation/Foundation.h>
#import <VideoToolbox/VideoToolbox.h>
#import <CoreVideo/CoreVideo.h>
#include <sys/wait.h>
#include <spawn.h>
extern char **environ;
#include <unistd.h>
#include <string.h>

typedef struct { const char *name; OSType src; int sw, sh; OSType dst; int dw, dh; int colorAttach; int realtime; } Case;

static const char *fourcc(OSType t, char b[5]) { b[0]=t>>24; b[1]=t>>16; b[2]=t>>8; b[3]=t; b[4]=0; return b; }

static CVPixelBufferRef makeBuf(OSType fmt, int w, int h, int colorAttach) {
    NSDictionary *attrs = @{ (id)kCVPixelBufferIOSurfacePropertiesKey: @{},
                             (id)kCVPixelBufferMetalCompatibilityKey: @YES };
    CVPixelBufferRef pb = NULL;
    CVReturn r = CVPixelBufferCreate(NULL, w, h, fmt, (__bridge CFDictionaryRef)attrs, &pb);
    if (r != kCVReturnSuccess) { printf("    CVPixelBufferCreate %d\n", r); return NULL; }
    CVPixelBufferLockBaseAddress(pb, 0);
    size_t planes = CVPixelBufferGetPlaneCount(pb);
    if (planes == 0) {
        uint8_t *p = CVPixelBufferGetBaseAddress(pb);
        size_t bpr = CVPixelBufferGetBytesPerRow(pb);
        for (int y = 0; y < h; y++) for (size_t x = 0; x < bpr; x++) p[y * bpr + x] = (uint8_t)(x ^ y);
    } else {
        for (size_t i = 0; i < planes; i++) {
            uint8_t *p = CVPixelBufferGetBaseAddressOfPlane(pb, i);
            size_t bpr = CVPixelBufferGetBytesPerRowOfPlane(pb, i), ph = CVPixelBufferGetHeightOfPlane(pb, i);
            for (size_t y = 0; y < ph; y++) for (size_t x = 0; x < bpr; x++) p[y * bpr + x] = (uint8_t)(i ? 128 + (x & 31) : (x + y));
        }
    }
    CVPixelBufferUnlockBaseAddress(pb, 0);
    if (colorAttach) { // what a hardware-decoded YouTube frame typically carries
        CVBufferSetAttachment(pb, kCVImageBufferColorPrimariesKey, kCVImageBufferColorPrimaries_ITU_R_709_2, kCVAttachmentMode_ShouldPropagate);
        CVBufferSetAttachment(pb, kCVImageBufferTransferFunctionKey, kCVImageBufferTransferFunction_ITU_R_709_2, kCVAttachmentMode_ShouldPropagate);
        CVBufferSetAttachment(pb, kCVImageBufferYCbCrMatrixKey, kCVImageBufferYCbCrMatrix_ITU_R_709_2, kCVAttachmentMode_ShouldPropagate);
    }
    return pb;
}

static int runCase(const Case *c, int iters) {
    VTPixelTransferSessionRef s = NULL;
    OSStatus st = VTPixelTransferSessionCreate(NULL, &s);
    if (st) { printf("    session create %d\n", (int)st); return 1; }
    if (c->realtime) VTSessionSetProperty(s, kVTPixelTransferPropertyKey_RealTime, kCFBooleanTrue);
    if (c->colorAttach) { // WebKit asks for sRGB destination
        VTSessionSetProperty(s, kVTPixelTransferPropertyKey_DestinationColorPrimaries, kCVImageBufferColorPrimaries_ITU_R_709_2);
        VTSessionSetProperty(s, kVTPixelTransferPropertyKey_DestinationTransferFunction, kCVImageBufferTransferFunction_sRGB);
    }
    CVPixelBufferRef src = makeBuf(c->src, c->sw, c->sh, c->colorAttach);
    CVPixelBufferRef dst = makeBuf(c->dst, c->dw, c->dh, 0);
    if (!src || !dst) return 1;
    CVPixelBufferLockBaseAddress(dst, 0);
    size_t dplanes = CVPixelBufferGetPlaneCount(dst) ? CVPixelBufferGetPlaneCount(dst) : 1;
    for (size_t i = 0; i < dplanes; i++) {
        uint8_t *p = CVPixelBufferGetPlaneCount(dst) ? CVPixelBufferGetBaseAddressOfPlane(dst, i) : CVPixelBufferGetBaseAddress(dst);
        size_t n = (CVPixelBufferGetPlaneCount(dst) ? CVPixelBufferGetBytesPerRowOfPlane(dst, i) * CVPixelBufferGetHeightOfPlane(dst, i)
                                                    : CVPixelBufferGetBytesPerRow(dst) * CVPixelBufferGetHeight(dst));
        memset(p, 0x5A, n);
    }
    CVPixelBufferUnlockBaseAddress(dst, 0);
    if (getenv("VTXFER_IDS")) {  // for correlating with the VA shim's os_log dumps (tools/va-shim)
        IOSurfaceRef ss = CVPixelBufferGetIOSurface(src), ds = CVPixelBufferGetIOSurface(dst);
        printf("\n    src IOSurface %p id %#x base %p | dst IOSurface %p id %#x base %p\n    ",
               ss, ss ? IOSurfaceGetID(ss) : 0, ss ? IOSurfaceGetBaseAddress(ss) : NULL,
               ds, ds ? IOSurfaceGetID(ds) : 0, ds ? IOSurfaceGetBaseAddress(ds) : NULL);
    }
    int errs = 0;
    for (int i = 0; i < iters; i++) {
        st = VTPixelTransferSessionTransferImage(s, src, dst);
        if (st) { if (errs < 3) printf("    iter %d status %d\n", i, (int)st); errs++; }
    }
    CVPixelBufferLockBaseAddress(dst, kCVPixelBufferLock_ReadOnly);
    size_t total = 0, written = 0; uint32_t sum = 0;
    for (size_t i = 0; i < dplanes; i++) {
        const uint8_t *p = CVPixelBufferGetPlaneCount(dst) ? CVPixelBufferGetBaseAddressOfPlane(dst, i) : CVPixelBufferGetBaseAddress(dst);
        size_t w = CVPixelBufferGetPlaneCount(dst) ? CVPixelBufferGetWidthOfPlane(dst, i) * (i ? 2 : 1) : CVPixelBufferGetWidth(dst) * 4;
        size_t h = CVPixelBufferGetPlaneCount(dst) ? CVPixelBufferGetHeightOfPlane(dst, i) : CVPixelBufferGetHeight(dst);
        size_t bpr = CVPixelBufferGetPlaneCount(dst) ? CVPixelBufferGetBytesPerRowOfPlane(dst, i) : CVPixelBufferGetBytesPerRow(dst);
        for (size_t y = 0; y < h; y++) for (size_t x = 0; x < w; x++) { uint8_t b = p[y * bpr + x]; total++; if (b != 0x5A) written++; sum = sum * 31 + b; }
    }
    const char *dumpdir = getenv("VTXFER_DUMP");  // raw dst planes (tight rows) for comparing against another machine
    if (dumpdir) {
        char path[1024];
        snprintf(path, sizeof path, "%s/%s.raw", dumpdir, c->name);
        FILE *fp = fopen(path, "wb");
        for (size_t i = 0; fp && i < dplanes; i++) {
            const uint8_t *p = CVPixelBufferGetPlaneCount(dst) ? CVPixelBufferGetBaseAddressOfPlane(dst, i) : CVPixelBufferGetBaseAddress(dst);
            size_t w = CVPixelBufferGetPlaneCount(dst) ? CVPixelBufferGetWidthOfPlane(dst, i) * (i ? 2 : 1) : CVPixelBufferGetWidth(dst) * 4;
            size_t h = CVPixelBufferGetPlaneCount(dst) ? CVPixelBufferGetHeightOfPlane(dst, i) : CVPixelBufferGetHeight(dst);
            size_t bpr = CVPixelBufferGetPlaneCount(dst) ? CVPixelBufferGetBytesPerRowOfPlane(dst, i) : CVPixelBufferGetBytesPerRow(dst);
            for (size_t y = 0; y < h; y++) fwrite(p + y * bpr, 1, w, fp);
        }
        if (fp) fclose(fp);
    }
    CVPixelBufferUnlockBaseAddress(dst, kCVPixelBufferLock_ReadOnly);
    printf("wrote %.1f%% sum %08x ", total ? 100.0 * written / total : 0.0, sum);
    fflush(stdout);
    VTPixelTransferSessionInvalidate(s);
    CFRelease(s); CVPixelBufferRelease(src); CVPixelBufferRelease(dst);
    return errs ? 1 : 0;
}

int main(int argc, char **argv) { @autoreleasepool {
    int one = -1;
    if (argc > 3 && !strcmp(argv[1], "--one")) { one = atoi(argv[2]); argv += 2; argc -= 2; }
    int iters = argc > 1 ? atoi(argv[1]) : 60;
    const char *filter = argc > 2 ? argv[2] : NULL;
    const OSType v = kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange, f = kCVPixelFormatType_420YpCbCr8BiPlanarFullRange,
                 x = kCVPixelFormatType_420YpCbCr10BiPlanarVideoRange, bgra = kCVPixelFormatType_32BGRA;
    Case cases[] = {
        {"bgra-copy",          bgra, 1920, 1080, bgra, 1920, 1080, 0, 0},
        {"bgra-scale",         bgra, 1920, 1080, bgra,  640,  360, 0, 0},
        {"420v-bgra",          v,    1920, 1080, bgra, 1920, 1080, 0, 0},
        {"420v-bgra-scale",    v,    1920, 1080, bgra,  640,  360, 0, 0},
        {"420v-bgra-709",      v,    1920, 1080, bgra, 1920, 1080, 1, 0},
        {"420v-bgra-709-scale",v,    1920, 1080, bgra,  640,  360, 1, 0},
        {"420v-bgra-709-rt",   v,    1920, 1080, bgra, 1920, 1080, 1, 1},
        {"420f-bgra",          f,    1920, 1080, bgra, 1920, 1080, 0, 0},
        {"x420-bgra",          x,    1920, 1080, bgra, 1920, 1080, 0, 0},
        {"420v-420v-scale",    v,    1920, 1080, v,     960,  540, 0, 0},
        {"420v-bgra-4k",       v,    3840, 2160, bgra, 3840, 2160, 1, 0},
    };
    int n = sizeof cases / sizeof cases[0], failed = 0;
    if (one >= 0) return runCase(&cases[one], iters);
    for (int i = 0; i < n; i++) {
        const Case *c = &cases[i];
        if (filter && !strstr(c->name, filter)) continue;
        char a[5], b[5];
        printf("%-22s %s %dx%d -> %s %dx%d color=%d rt=%d ... ", c->name, fourcc(c->src, a), c->sw, c->sh,
               fourcc(c->dst, b), c->dw, c->dh, c->colorAttach, c->realtime);
        fflush(stdout);
        char idx[16], it[16]; snprintf(idx, sizeof idx, "%d", i); snprintf(it, sizeof it, "%d", iters);
        char *cargv[] = { argv[0], "--one", idx, it, NULL };
        pid_t pid; int ws = 0;
        if (posix_spawn(&pid, argv[0], NULL, NULL, cargv, environ)) { perror("posix_spawn"); return 2; }
        waitpid(pid, &ws, 0);
        if (WIFSIGNALED(ws)) { printf("CRASH signal %d\n", WTERMSIG(ws)); failed++; }
        else if (WEXITSTATUS(ws)) { printf("ERRORS\n"); failed++; }
        else printf("ok\n");
    }
    printf("%d case(s) failed\n", failed);
    return failed ? 1 : 0;
}}
