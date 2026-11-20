// gpucheck: verify Metal compute/render actually run correctly on the GPU, and report HW video decode support.
// Usage: gpucheck [stress-seconds]
// Build: clang -arch x86_64 -mmacosx-version-min=26.0 -fobjc-arc -framework Metal -framework Foundation \
//        -framework VideoToolbox -framework CoreMedia -o gpucheck gpucheck.m
#import <Metal/Metal.h>
#import <Foundation/Foundation.h>
#import <VideoToolbox/VideoToolbox.h>
#include <mach/mach_time.h>

static NSString *const kSrc = @
"#include <metal_stdlib>\n"
"using namespace metal;\n"
"kernel void vadd(device const float *a [[buffer(0)]], device const float *b [[buffer(1)]],\n"
"                 device float *c [[buffer(2)]], uint i [[thread_position_in_grid]]) { c[i] = a[i] * 2.0f + b[i]; }\n"
"kernel void burn(device float *c [[buffer(0)]], uint i [[thread_position_in_grid]]) {\n"
"  float x = c[i]; for (int k = 0; k < 4096; k++) { x = fma(x, 1.000001f, 0.5f); x = x - floor(x); } c[i] = x; }\n"
"struct VO { float4 pos [[position]]; float4 col; };\n"
"vertex VO vmain(uint vid [[vertex_id]]) {\n"
"  float2 p[3] = { float2(-1,-1), float2(3,-1), float2(-1,3) }; VO o; o.pos = float4(p[vid],0,1);\n"
"  o.col = float4(0.25, 0.5, 0.75, 1.0); return o; }\n"
"fragment float4 fmain(VO in [[stage_in]]) { return in.col; }\n";

static double secs(uint64_t t) { static mach_timebase_info_data_t tb; if (!tb.denom) mach_timebase_info(&tb); return (double)t * tb.numer / tb.denom / 1e9; }

int main(int argc, char **argv) { @autoreleasepool {
    double stress = argc > 1 ? atof(argv[1]) : 0;
    NSArray<id<MTLDevice>> *all = MTLCopyAllDevices();
    printf("Metal devices: %lu\n", (unsigned long)all.count);
    id<MTLDevice> dev = MTLCreateSystemDefaultDevice();
    if (!dev) { printf("FAIL: no default Metal device\n"); return 1; }
    printf("device: %s  lowPower=%d headless=%d unified=%d\n", dev.name.UTF8String, dev.lowPower, dev.headless, dev.hasUnifiedMemory);
    printf("recommendedMaxWorkingSet=%.0f MB  maxBuffer=%.0f MB  maxThreadsPerTG=%lu\n",
           dev.recommendedMaxWorkingSetSize / 1048576.0, dev.maxBufferLength / 1048576.0,
           (unsigned long)dev.maxThreadsPerThreadgroup.width);
    const MTLGPUFamily fams[] = { MTLGPUFamilyMac2, MTLGPUFamilyCommon1, MTLGPUFamilyCommon2, MTLGPUFamilyCommon3, MTLGPUFamilyMetal3 };
    const char *fn[] = { "Mac2", "Common1", "Common2", "Common3", "Metal3" };
    printf("families:"); for (int i = 0; i < 5; i++) printf(" %s=%d", fn[i], [dev supportsFamily:fams[i]]); printf("\n");

    NSError *err = nil;
    uint64_t t = mach_absolute_time();
    id<MTLLibrary> lib = [dev newLibraryWithSource:kSrc options:nil error:&err];
    if (!lib) { printf("FAIL: shader compile: %s\n", err.localizedDescription.UTF8String); return 1; }
    printf("shader compile: %.1f ms\n", secs(mach_absolute_time() - t) * 1e3);
    id<MTLCommandQueue> q = [dev newCommandQueue];
    int fails = 0;

    // ---- compute correctness + bandwidth-ish timing ----
    const NSUInteger N = 16 * 1024 * 1024;
    id<MTLBuffer> A = [dev newBufferWithLength:N * 4 options:MTLResourceStorageModeShared];
    id<MTLBuffer> B = [dev newBufferWithLength:N * 4 options:MTLResourceStorageModeShared];
    id<MTLBuffer> C = [dev newBufferWithLength:N * 4 options:MTLResourceStorageModeShared];
    float *a = A.contents, *b = B.contents, *c = C.contents;
    for (NSUInteger i = 0; i < N; i++) { a[i] = (float)(i % 1000); b[i] = (float)(i % 7); c[i] = -1; }
    id<MTLComputePipelineState> vadd = [dev newComputePipelineStateWithFunction:[lib newFunctionWithName:@"vadd"] error:&err];
    double best = 1e9;
    for (int r = 0; r < 5; r++) {
        id<MTLCommandBuffer> cb = [q commandBuffer];
        id<MTLComputeCommandEncoder> e = [cb computeCommandEncoder];
        [e setComputePipelineState:vadd]; [e setBuffer:A offset:0 atIndex:0]; [e setBuffer:B offset:0 atIndex:1]; [e setBuffer:C offset:0 atIndex:2];
        [e dispatchThreads:MTLSizeMake(N, 1, 1) threadsPerThreadgroup:MTLSizeMake(vadd.maxTotalThreadsPerThreadgroup, 1, 1)];
        [e endEncoding]; [cb commit]; [cb waitUntilCompleted];
        if (cb.error) { printf("FAIL: compute cb error: %s\n", cb.error.localizedDescription.UTF8String); return 1; }
        double g = cb.GPUEndTime - cb.GPUStartTime; if (g < best) best = g;
    }
    NSUInteger bad = 0;
    for (NSUInteger i = 0; i < N; i++) if (c[i] != a[i] * 2.0f + b[i]) { if (bad < 3) printf("  mismatch @%lu: %f\n", (unsigned long)i, c[i]); bad++; }
    printf("compute vadd %lu elems: %s (bad=%lu)  GPU %.2f ms  ~%.1f GB/s\n", (unsigned long)N, bad ? "FAIL" : "OK",
           (unsigned long)bad, best * 1e3, (N * 12.0) / best / 1e9);
    fails += bad != 0;

    // ---- render to offscreen texture + readback ----
    MTLRenderPipelineDescriptor *rp = [MTLRenderPipelineDescriptor new];
    rp.vertexFunction = [lib newFunctionWithName:@"vmain"]; rp.fragmentFunction = [lib newFunctionWithName:@"fmain"];
    rp.colorAttachments[0].pixelFormat = MTLPixelFormatRGBA8Unorm;
    id<MTLRenderPipelineState> rps = [dev newRenderPipelineStateWithDescriptor:rp error:&err];
    if (!rps) { printf("FAIL: render pipeline: %s\n", err.localizedDescription.UTF8String); return 1; }
    MTLTextureDescriptor *td = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA8Unorm width:1024 height:1024 mipmapped:NO];
    td.usage = MTLTextureUsageRenderTarget; td.storageMode = MTLStorageModeManaged;
    id<MTLTexture> tex = [dev newTextureWithDescriptor:td];
    MTLRenderPassDescriptor *pass = [MTLRenderPassDescriptor renderPassDescriptor];
    pass.colorAttachments[0].texture = tex; pass.colorAttachments[0].loadAction = MTLLoadActionClear;
    pass.colorAttachments[0].clearColor = MTLClearColorMake(1, 0, 0, 1); pass.colorAttachments[0].storeAction = MTLStoreActionStore;
    id<MTLCommandBuffer> cb = [q commandBuffer];
    id<MTLRenderCommandEncoder> re = [cb renderCommandEncoderWithDescriptor:pass];
    [re setRenderPipelineState:rps]; [re drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3]; [re endEncoding];
    id<MTLBlitCommandEncoder> bl = [cb blitCommandEncoder]; [bl synchronizeResource:tex]; [bl endEncoding];
    [cb commit]; [cb waitUntilCompleted];
    if (cb.error) { printf("FAIL: render cb error: %s\n", cb.error.localizedDescription.UTF8String); return 1; }
    uint8_t *px = malloc(1024 * 1024 * 4);
    [tex getBytes:px bytesPerRow:4096 fromRegion:MTLRegionMake2D(0, 0, 1024, 1024) mipmapLevel:0];
    NSUInteger rbad = 0;
    for (NSUInteger i = 0; i < 1024 * 1024; i++) {
        uint8_t *p = px + i * 4;
        if (abs(p[0] - 64) > 1 || abs(p[1] - 128) > 1 || abs(p[2] - 191) > 1 || p[3] != 255) rbad++;
    }
    printf("render 1024x1024 fullscreen tri: %s (bad px=%lu, px0=%d,%d,%d,%d)\n", rbad ? "FAIL" : "OK", (unsigned long)rbad, px[0], px[1], px[2], px[3]);
    fails += rbad != 0;

    // ---- HW video decode support ----
    struct { CMVideoCodecType t; const char *n; } codecs[] = {
        { kCMVideoCodecType_H264, "H.264" }, { kCMVideoCodecType_HEVC, "HEVC" },
        { kCMVideoCodecType_VP9, "VP9" }, { kCMVideoCodecType_AV1, "AV1" }, { kCMVideoCodecType_JPEG, "JPEG" } };
    printf("VTIsHardwareDecodeSupported:");
    for (int i = 0; i < 5; i++) printf(" %s=%d", codecs[i].n, VTIsHardwareDecodeSupported(codecs[i].t));
    printf("\n");

    // ---- stress: long compute bursts, check every command buffer ----
    if (stress > 0) {
        id<MTLComputePipelineState> burn = [dev newComputePipelineStateWithFunction:[lib newFunctionWithName:@"burn"] error:&err];
        uint64_t s0 = mach_absolute_time(); int n = 0, errs = 0; double gpu = 0, worst = 0;
        while (secs(mach_absolute_time() - s0) < stress) {
            id<MTLCommandBuffer> sb = [q commandBuffer];
            id<MTLComputeCommandEncoder> e = [sb computeCommandEncoder];
            [e setComputePipelineState:burn]; [e setBuffer:C offset:0 atIndex:0];
            [e dispatchThreads:MTLSizeMake(1024 * 1024, 1, 1) threadsPerThreadgroup:MTLSizeMake(burn.maxTotalThreadsPerThreadgroup, 1, 1)];
            [e endEncoding]; [sb commit]; [sb waitUntilCompleted];
            if (sb.error) { errs++; if (errs < 4) printf("  stress cb error #%d: %s\n", n, sb.error.localizedDescription.UTF8String); }
            double g = sb.GPUEndTime - sb.GPUStartTime; gpu += g; if (g > worst) worst = g; n++;
        }
        double wall = secs(mach_absolute_time() - s0);
        printf("stress %.0fs: %d cmdbufs, errors=%d, GPU busy %.0f%%, avg %.1f ms, worst %.1f ms\n",
               wall, n, errs, gpu / wall * 100, gpu / n * 1e3, worst * 1e3);
        fails += errs != 0;
    }
    printf("RESULT: %s\n", fails ? "FAIL" : "PASS");
    return fails ? 1 : 0;
}}
