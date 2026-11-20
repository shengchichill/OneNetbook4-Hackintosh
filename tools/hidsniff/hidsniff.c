// hidsniff: open HID devices by vendor ID (non-exclusive) and dump raw input reports.
// Usage: hidsniff <vendorID-hex> [seconds] [featureReportID...]
// Build: clang -arch x86_64 -mmacosx-version-min=26.0 -framework IOKit -framework CoreFoundation -o hidsniff hidsniff.c
#include <IOKit/hid/IOHIDManager.h>
#include <CoreFoundation/CoreFoundation.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

static uint8_t bufs[16][1024];
static int nbuf = 0;
static int counts[256];

static double now(void) {
    struct timespec ts; clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec + ts.tv_nsec / 1e9;
}
static double t0;

static void onReport(void *ctx, IOReturn res, void *sender, IOHIDReportType type,
                     uint32_t reportID, uint8_t *report, CFIndex len) {
    counts[reportID & 0xff]++;
    if (counts[reportID & 0xff] > 40) return;   // avoid flooding
    printf("%8.3f id=%u type=%d len=%ld :", now() - t0, reportID, type, (long)len);
    for (CFIndex i = 0; i < len && i < 64; i++) printf(" %02x", report[i]);
    printf("\n");
    fflush(stdout);
}

static int getInt(IOHIDDeviceRef d, CFStringRef key) {
    int v = -1; CFTypeRef r = IOHIDDeviceGetProperty(d, key);
    if (r && CFGetTypeID(r) == CFNumberGetTypeID()) CFNumberGetValue(r, kCFNumberIntType, &v);
    return v;
}

int main(int argc, char **argv) {
    if (argc < 2) { fprintf(stderr, "usage: %s <vid-hex> [seconds] [featureID...]\n", argv[0]); return 2; }
    int vid = (int)strtol(argv[1], NULL, 16);
    double secs = argc > 2 ? atof(argv[2]) : 20;
    t0 = now();

    IOHIDManagerRef m = IOHIDManagerCreate(kCFAllocatorDefault, kIOHIDOptionsTypeNone);
    CFMutableDictionaryRef match = CFDictionaryCreateMutable(NULL, 0, &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
    CFNumberRef n = CFNumberCreate(NULL, kCFNumberIntType, &vid);
    CFDictionarySetValue(match, CFSTR(kIOHIDVendorIDKey), n);
    IOHIDManagerSetDeviceMatching(m, match);
    IOReturn r = IOHIDManagerOpen(m, kIOHIDOptionsTypeNone);
    printf("IOHIDManagerOpen = 0x%x\n", r);

    CFSetRef set = IOHIDManagerCopyDevices(m);
    if (!set) { printf("no devices for vid 0x%x\n", vid); return 1; }
    CFIndex cnt = CFSetGetCount(set);
    IOHIDDeviceRef devs[16];
    CFSetGetValues(set, (const void **)devs);
    for (CFIndex i = 0; i < cnt && i < 16; i++) {
        IOHIDDeviceRef d = devs[i];
        printf("dev %ld: vid=0x%x pid=0x%x usagePage=0x%x usage=0x%x\n", (long)i,
               getInt(d, CFSTR(kIOHIDVendorIDKey)), getInt(d, CFSTR(kIOHIDProductIDKey)),
               getInt(d, CFSTR(kIOHIDPrimaryUsagePageKey)), getInt(d, CFSTR(kIOHIDPrimaryUsageKey)));
        IOReturn o = IOHIDDeviceOpen(d, kIOHIDOptionsTypeNone);
        printf("  IOHIDDeviceOpen = 0x%x\n", o);
        for (int a = 3; a < argc; a++) {
            int fid = (int)strtol(argv[a], NULL, 0);
            uint8_t fb[300] = {0}; CFIndex fl = sizeof(fb);
            fb[0] = (uint8_t)fid;
            IOReturn g = IOHIDDeviceGetReport(d, kIOHIDReportTypeFeature, fid, fb, &fl);
            printf("  feature %d: ret=0x%x len=%ld :", fid, g, (long)fl);
            for (CFIndex k = 0; g == kIOReturnSuccess && k < fl && k < 32; k++) printf(" %02x", fb[k]);
            printf("\n");
        }
        if (nbuf < 16) {
            IOHIDDeviceRegisterInputReportCallback(d, bufs[nbuf], sizeof(bufs[0]), onReport, NULL);
            nbuf++;
        }
        IOHIDDeviceScheduleWithRunLoop(d, CFRunLoopGetCurrent(), kCFRunLoopDefaultMode);
    }
    printf("listening %.0f s ... touch the trackpad now\n", secs);
    fflush(stdout);
    CFRunLoopRunInMode(kCFRunLoopDefaultMode, secs, false);
    printf("done. report counts:");
    for (int i = 0; i < 256; i++) if (counts[i]) printf(" id%d=%d", i, counts[i]);
    printf("\n");
    return 0;
}
