// swconvert: CPU pixel transfer for the VA shim (route ③, Step 2).
// Does what the TGL VA driver's VHAL_VideoProcessor should have done for a fn 0x3ea command:
// copy/convert/scale src IOSurface (srcRect) into dst IOSurface (dstRect) with vImage.
// Supported: BGRA -> BGRA, 420v/420f -> BGRA, 420v/420f -> 420v/420f (scale only; range is not converted).
// Anything else returns -1 and leaves dst untouched (same as today's "success without writing").
#include "swconvert.h"
#include <Accelerate/Accelerate.h>
#include <CoreFoundation/CoreFoundation.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define FCC(a, b, c, d) (((uint32_t)(a) << 24) | ((uint32_t)(b) << 16) | ((uint32_t)(c) << 8) | (uint32_t)(d))
#define F_BGRA FCC('B', 'G', 'R', 'A')
#define F_420V FCC('4', '2', '0', 'v')
#define F_420F FCC('4', '2', '0', 'f')

typedef struct { long x, y, w, h; } irect;

// rect (x,y,w,h doubles) -> integer rect clamped to the surface; even-aligned for 4:2:0
static int to_irect(const double r[4], size_t sw, size_t sh, int even, irect *o) {
    double x = r[0], y = r[1], w = r[2], h = r[3];
    if (!(w > 0) || !(h > 0)) { x = 0; y = 0; w = (double)sw; h = (double)sh; }  // empty rect = whole surface
    long ix = lround(x), iy = lround(y), iw = lround(w), ih = lround(h);
    if (ix < 0) { iw += ix; ix = 0; }
    if (iy < 0) { ih += iy; iy = 0; }
    if (ix + iw > (long)sw) iw = (long)sw - ix;
    if (iy + ih > (long)sh) ih = (long)sh - iy;
    if (even) { ix &= ~1L; iy &= ~1L; iw &= ~1L; ih &= ~1L; }
    if (iw <= 0 || ih <= 0) return 0;
    *o = (irect){ix, iy, iw, ih};
    return 1;
}

static vImage_Buffer plane(IOSurfaceRef s, size_t p, long x, long y, long w, long h, size_t bpp) {
    uint8_t *base = IOSurfaceGetPlaneCount(s) ? IOSurfaceGetBaseAddressOfPlane(s, p) : IOSurfaceGetBaseAddress(s);
    size_t bpr = IOSurfaceGetPlaneCount(s) ? IOSurfaceGetBytesPerRowOfPlane(s, p) : IOSurfaceGetBytesPerRow(s);
    return (vImage_Buffer){base + (size_t)y * bpr + (size_t)x * bpp, (vImagePixelCount)h, (vImagePixelCount)w, bpr};
}

// Find a CoreVideo attachment value: CoreVideo stores propagated attachments on the IOSurface,
// either at top level or inside a nested dictionary depending on the OS; search one level down.
static int find_string(CFDictionaryRef d, CFStringRef key, char *out, size_t n, int depth) {
    CFTypeRef v = CFDictionaryGetValue(d, key);
    if (v && CFGetTypeID(v) == CFStringGetTypeID()) return CFStringGetCString(v, out, (CFIndex)n, kCFStringEncodingUTF8);
    if (depth <= 0) return 0;
    CFIndex c = CFDictionaryGetCount(d);
    if (c <= 0 || c > 256) return 0;
    const void **vals = calloc((size_t)c, sizeof *vals);
    if (!vals) return 0;
    CFDictionaryGetKeysAndValues(d, NULL, vals);
    int found = 0;
    for (CFIndex i = 0; i < c && !found; i++)
        if (vals[i] && CFGetTypeID(vals[i]) == CFDictionaryGetTypeID()) found = find_string(vals[i], key, out, n, depth - 1);
    free(vals);
    return found;
}

static const vImage_YpCbCrToARGBMatrix *pick_matrix(IOSurfaceRef src, size_t h, const char **name) {
    char m[64] = "";
    CFDictionaryRef all = IOSurfaceCopyAllValues(src);
    if (all) { find_string(all, CFSTR("CVImageBufferYCbCrMatrix"), m, sizeof m, 2); CFRelease(all); }
    if (strstr(m, "601")) { *name = "601"; return kvImage_YpCbCrToARGBMatrix_ITU_R_601_4; }
    if (strstr(m, "709")) { *name = "709"; return kvImage_YpCbCrToARGBMatrix_ITU_R_709_2; }
    // no tag (or 2020/SMPTE240, not handled): usual convention, SD = 601, HD = 709
    *name = h >= 720 ? "709?" : "601?";
    return h >= 720 ? kvImage_YpCbCrToARGBMatrix_ITU_R_709_2 : kvImage_YpCbCrToARGBMatrix_ITU_R_601_4;
}

static int yuv_to_bgra(IOSurfaceRef src, irect sr, vImage_Buffer *out, char *why, size_t n) {
    uint32_t sf = IOSurfaceGetPixelFormat(src);
    const char *mname;
    const vImage_YpCbCrToARGBMatrix *mat = pick_matrix(src, IOSurfaceGetHeight(src), &mname);
    vImage_YpCbCrPixelRange video = {16, 128, 235, 240, 235, 16, 240, 16};
    vImage_YpCbCrPixelRange full = {0, 128, 255, 255, 255, 1, 255, 0};
    vImage_YpCbCrToARGB info;
    vImage_Error e = vImageConvert_YpCbCrToARGB_GenerateConversion(mat, sf == F_420F ? &full : &video, &info,
                                                                   kvImage420Yp8_CbCr8, kvImageARGB8888, kvImageNoFlags);
    if (e != kvImageNoError) { snprintf(why, n, "GenerateConversion %ld", e); return -1; }
    vImage_Buffer y = plane(src, 0, sr.x, sr.y, sr.w, sr.h, 1);
    vImage_Buffer c = plane(src, 1, sr.x / 2, sr.y / 2, sr.w / 2, sr.h / 2, 2);
    const uint8_t bgra[4] = {3, 2, 1, 0};  // ARGB -> BGRA
    e = vImageConvert_420Yp8_CbCr8ToARGB8888(&y, &c, out, &info, bgra, 255, kvImageNoFlags);
    if (e != kvImageNoError) { snprintf(why, n, "420->ARGB %ld", e); return -1; }
    snprintf(why, n, "matrix %s %s", mname, sf == F_420F ? "full" : "video");
    return 0;
}

int vashim_convert(IOSurfaceRef src, const double srcRect[4], IOSurfaceRef dst, const double dstRect[4], char *why, size_t n) {
    uint32_t sf = IOSurfaceGetPixelFormat(src), df = IOSurfaceGetPixelFormat(dst);
    int syuv = sf == F_420V || sf == F_420F, dyuv = df == F_420V || df == F_420F;
    if (!((sf == F_BGRA || syuv) && (df == F_BGRA || dyuv)) || (sf == F_BGRA && dyuv)) {
        snprintf(why, n, "unsupported %.4s -> %.4s", (char[]){sf >> 24, sf >> 16, sf >> 8, sf},
                 (char[]){df >> 24, df >> 16, df >> 8, df});
        return -1;
    }
    irect sr, dr;
    if (!to_irect(srcRect, IOSurfaceGetWidth(src), IOSurfaceGetHeight(src), syuv, &sr) ||
        !to_irect(dstRect, IOSurfaceGetWidth(dst), IOSurfaceGetHeight(dst), dyuv, &dr)) {
        snprintf(why, n, "empty rect");
        return -1;
    }
    int rc = -1;
    void *tmp = NULL;
    if (IOSurfaceLock(src, kIOSurfaceLockReadOnly, NULL) != kIOReturnSuccess) { snprintf(why, n, "lock src"); return -1; }
    if (IOSurfaceLock(dst, 0, NULL) != kIOReturnSuccess) { IOSurfaceUnlock(src, kIOSurfaceLockReadOnly, NULL); snprintf(why, n, "lock dst"); return -1; }
    int same = sr.w == dr.w && sr.h == dr.h;
    vImage_Error e = kvImageNoError;
    snprintf(why, n, "ok");

    if (sf == F_BGRA) {  // BGRA -> BGRA
        vImage_Buffer s = plane(src, 0, sr.x, sr.y, sr.w, sr.h, 4), d = plane(dst, 0, dr.x, dr.y, dr.w, dr.h, 4);
        if (same) for (long r = 0; r < sr.h; r++) memcpy((uint8_t *)d.data + r * d.rowBytes, (uint8_t *)s.data + r * s.rowBytes, (size_t)sr.w * 4);
        else e = vImageScale_ARGB8888(&s, &d, NULL, kvImageHighQualityResampling);
        rc = e == kvImageNoError ? 0 : -1;
    } else if (df == F_BGRA) {  // 420 -> BGRA (convert at source size, then scale if needed)
        vImage_Buffer d = plane(dst, 0, dr.x, dr.y, dr.w, dr.h, 4);
        if (same) rc = yuv_to_bgra(src, sr, &d, why, n);
        else {
            size_t bpr = ((size_t)sr.w * 4 + 63) & ~(size_t)63;
            tmp = malloc(bpr * (size_t)sr.h);
            if (tmp) {
                vImage_Buffer t = {tmp, (vImagePixelCount)sr.h, (vImagePixelCount)sr.w, bpr};
                rc = yuv_to_bgra(src, sr, &t, why, n);
                if (!rc) { e = vImageScale_ARGB8888(&t, &d, NULL, kvImageHighQualityResampling); rc = e == kvImageNoError ? 0 : -1; }
            } else snprintf(why, n, "malloc");
        }
    } else {  // 420 -> 420 (planes scaled independently; range not converted)
        vImage_Buffer sy = plane(src, 0, sr.x, sr.y, sr.w, sr.h, 1), dy = plane(dst, 0, dr.x, dr.y, dr.w, dr.h, 1);
        vImage_Buffer sc = plane(src, 1, sr.x / 2, sr.y / 2, sr.w / 2, sr.h / 2, 2), dc = plane(dst, 1, dr.x / 2, dr.y / 2, dr.w / 2, dr.h / 2, 2);
        if (same) {
            for (long r = 0; r < sr.h; r++) memcpy((uint8_t *)dy.data + r * dy.rowBytes, (uint8_t *)sy.data + r * sy.rowBytes, (size_t)sr.w);
            for (long r = 0; r < sr.h / 2; r++) memcpy((uint8_t *)dc.data + r * dc.rowBytes, (uint8_t *)sc.data + r * sc.rowBytes, (size_t)sr.w);
        } else {
            e = vImageScale_Planar8(&sy, &dy, NULL, kvImageHighQualityResampling);
            if (e == kvImageNoError) e = vImageScale_CbCr8(&sc, &dc, NULL, kvImageHighQualityResampling);
        }
        rc = e == kvImageNoError ? 0 : -1;
        if (sf != df) snprintf(why, n, "ok (range not converted)");
    }
    if (rc && e != kvImageNoError) snprintf(why, n, "vImage %ld", e);
    free(tmp);
    IOSurfaceUnlock(dst, 0, NULL);
    IOSurfaceUnlock(src, kIOSurfaceLockReadOnly, NULL);
    return rc;
}
