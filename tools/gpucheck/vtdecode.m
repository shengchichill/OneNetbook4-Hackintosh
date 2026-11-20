// vtdecode: decode every video frame of a file with VideoToolbox, REQUIRING the hardware decoder.
// Usage: vtdecode <file.mp4> [--any|--sw] [hashes.txt]
//   default: require the hardware decoder; --any: let VideoToolbox pick; --sw: forbid hardware.
//   Output is the decoder's native format (no pixel transfer). Every frame's luma plane is hashed (FNV-1a) by PTS;
//   with a hashes file the list is written there, so a HW run and a --sw run can be diffed (H.264/HEVC are bit-exact).
//   "flat" counts frames whose luma is a single value (e.g. an unwritten buffer).
//   VTDECODE_FMT=<fourcc> (e.g. 420v, BGRA) asks for that output format instead (the decoder may then convert
//   internally, which is what Music/AVPlayer do; for BGRA the hash covers all four channels).
// Build: clang -arch x86_64 -mmacosx-version-min=26.0 -fobjc-arc -framework Foundation -framework AVFoundation \
//        -framework VideoToolbox -framework CoreMedia -framework CoreVideo -o vtdecode vtdecode.m
#import <AVFoundation/AVFoundation.h>
#import <VideoToolbox/VideoToolbox.h>
#include <mach/mach_time.h>

static int ok = 0, bad = 0, flat = 0;
static OSType outFmt = 0;
static NSMutableDictionary<NSNumber *, NSNumber *> *hashes;
static void cb(void *r, void *s, OSStatus st, VTDecodeInfoFlags f, CVImageBufferRef img, CMTime pts, CMTime dur) {
    if (st != noErr || !img) { if (bad < 3) printf("  frame error %d\n", (int)st); bad++; return; }
    CVPixelBufferRef pb = (CVPixelBufferRef)img;
    CVPixelBufferLockBaseAddress(pb, kCVPixelBufferLock_ReadOnly);
    BOOL planar = CVPixelBufferGetPlaneCount(pb) > 0;
    const uint8_t *y = planar ? CVPixelBufferGetBaseAddressOfPlane(pb, 0) : CVPixelBufferGetBaseAddress(pb);
    size_t bpr = planar ? CVPixelBufferGetBytesPerRowOfPlane(pb, 0) : CVPixelBufferGetBytesPerRow(pb);
    size_t h = planar ? CVPixelBufferGetHeightOfPlane(pb, 0) : CVPixelBufferGetHeight(pb);
    OSType pf = CVPixelBufferGetPixelFormatType(pb);
    BOOL eightBit = pf == kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange || pf == kCVPixelFormatType_420YpCbCr8BiPlanarFullRange;
    size_t wb = planar ? CVPixelBufferGetWidthOfPlane(pb, 0) * (eightBit ? 1 : 2) : CVPixelBufferGetWidth(pb) * 4;
    uint64_t hsh = 1469598103934665603ULL; uint8_t first = y ? y[0] : 0; BOOL same = YES;
    for (size_t row = 0; y && row < h; row++) for (size_t x = 0; x < wb; x++) { uint8_t b = y[row * bpr + x]; hsh = (hsh ^ b) * 1099511628211ULL; if (b != first) same = NO; }
    CVPixelBufferUnlockBaseAddress(pb, kCVPixelBufferLock_ReadOnly);
    @synchronized (hashes) {
        if (!outFmt) outFmt = CVPixelBufferGetPixelFormatType(pb);
        hashes[@(CMTimeGetSeconds(pts))] = @(hsh);
        if (same) flat++;
        ok++;
    }
}
static double secs(uint64_t t) { mach_timebase_info_data_t tb; mach_timebase_info(&tb); return (double)t * tb.numer / tb.denom / 1e9; }

int main(int argc, char **argv) { @autoreleasepool {
    if (argc < 2) { fprintf(stderr, "usage: %s file [--any]\n", argv[0]); return 2; }
    BOOL any = argc > 2 && !strcmp(argv[2], "--any"), sw = argc > 2 && !strcmp(argv[2], "--sw");
    const char *hashFile = argc > 3 ? argv[3] : (argc > 2 && argv[2][0] != '-' ? argv[2] : NULL);
    hashes = [NSMutableDictionary dictionary];
    AVURLAsset *asset = [AVURLAsset URLAssetWithURL:[NSURL fileURLWithPath:@(argv[1])] options:nil];
    __block NSArray<AVAssetTrack *> *tracks = nil;
    dispatch_semaphore_t sem = dispatch_semaphore_create(0);
    [asset loadTracksWithMediaType:AVMediaTypeVideo completionHandler:^(NSArray<AVAssetTrack *> *t, NSError *e) { tracks = t; dispatch_semaphore_signal(sem); }];
    dispatch_semaphore_wait(sem, DISPATCH_TIME_FOREVER);
    if (!tracks.count) { printf("FAIL: no video track\n"); return 1; }
    AVAssetTrack *track = tracks[0];
    NSError *err = nil;
    AVAssetReader *rd = [AVAssetReader assetReaderWithAsset:asset error:&err];
    AVAssetReaderTrackOutput *out = [AVAssetReaderTrackOutput assetReaderTrackOutputWithTrack:track outputSettings:nil]; // compressed passthrough
    [rd addOutput:out]; [rd startReading];

    VTDecompressionSessionRef sess = NULL;
    CMFormatDescriptionRef fmt = NULL;
    uint64_t t0 = 0; int n = 0;
    CMSampleBufferRef sb;
    while ((sb = [out copyNextSampleBuffer])) {
        if (CMSampleBufferGetNumSamples(sb) == 0 || !CMSampleBufferGetFormatDescription(sb)) { CFRelease(sb); continue; }
        if (!sess) {
            fmt = CMSampleBufferGetFormatDescription(sb);
            FourCharCode c = CMFormatDescriptionGetMediaSubType(fmt);
            CMVideoDimensions d = CMVideoFormatDescriptionGetDimensions(fmt);
            printf("codec %c%c%c%c %dx%d\n", (c >> 24) & 255, (c >> 16) & 255, (c >> 8) & 255, c & 255, d.width, d.height);
            NSDictionary *spec = any ? @{} : sw ? @{ (id)kVTVideoDecoderSpecification_EnableHardwareAcceleratedVideoDecoder: @NO }
                                              : @{ (id)kVTVideoDecoderSpecification_RequireHardwareAcceleratedVideoDecoder: @YES };
            VTDecompressionOutputCallbackRecord rec = { cb, NULL };
            NSDictionary *dstAttrs = nil;
            const char *want = getenv("VTDECODE_FMT");
            if (want && strlen(want) == 4) {
                OSType w = ((OSType)want[0] << 24) | ((OSType)want[1] << 16) | ((OSType)want[2] << 8) | (OSType)want[3];
                dstAttrs = @{ (id)kCVPixelBufferPixelFormatTypeKey: @(w), (id)kCVPixelBufferIOSurfacePropertiesKey: @{} };
                printf("requested output %s\n", want);
            }
            OSStatus st = VTDecompressionSessionCreate(NULL, fmt, (__bridge CFDictionaryRef)spec, (__bridge CFDictionaryRef)dstAttrs, &rec, &sess);
            if (st) { printf("FAIL: decoder session create = %d\n", (int)st); return 1; }
            CFBooleanRef hw = NULL;
            VTSessionCopyProperty(sess, kVTDecompressionPropertyKey_UsingHardwareAcceleratedVideoDecoder, NULL, &hw);
            printf("UsingHardwareAcceleratedVideoDecoder = %s\n", hw == kCFBooleanTrue ? "YES" : "NO");
            t0 = mach_absolute_time();
        }
        if (CMSampleBufferGetNumSamples(sb) > 0) {
            VTDecompressionSessionDecodeFrame(sess, sb, kVTDecodeFrame_EnableAsynchronousDecompression, NULL, NULL);
            n++;
        }
        CFRelease(sb);
    }
    if (sess) VTDecompressionSessionWaitForAsynchronousFrames(sess);
    double t = secs(mach_absolute_time() - t0);
    printf("submitted %d, decoded ok %d, errors %d, %.2f s, %.0f fps  reader status %ld\n", n, ok, bad, t, ok / t, (long)rd.status);
    NSArray *keys = [hashes.allKeys sortedArrayUsingSelector:@selector(compare:)];
    uint64_t all = 1469598103934665603ULL;
    NSMutableString *list = [NSMutableString string];
    for (NSNumber *k in keys) { uint64_t v = hashes[k].unsignedLongLongValue; all = (all ^ v) * 1099511628211ULL; [list appendFormat:@"%.6f %016llx\n", k.doubleValue, v]; }
    char fc[5] = { outFmt >> 24, outFmt >> 16, outFmt >> 8, outFmt, 0 };
    printf("output format %s, flat frames %d, frames hashed %lu, combined luma hash %016llx\n", fc, flat, (unsigned long)keys.count, all);
    if (hashFile) [list writeToFile:@(hashFile) atomically:YES encoding:NSUTF8StringEncoding error:nil];
    printf("RESULT: %s\n", (bad == 0 && ok == n && n > 0 && flat == 0) ? "PASS" : "FAIL");
    return 0;
}}
