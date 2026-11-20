// hidrate: count raw HID input reports per second for one vendor ID (non-exclusive open).
// Prints one line per second that had reports: "HH:MM:SS n=<count> [first report bytes]".
// Seconds without reports are summarized as "HH:MM:SS .. HH:MM:SS idle" when reports resume.
// Usage: hidrate <vendorID-hex> [seconds] [-v]     e.g. hidrate 27c6 3600   (GXTP7386 touchscreen)
//   -v: also print every report as "HH:MM:SS.mmm +gap_ms : bytes" (for timing analysis)
// Build: clang -arch x86_64 -mmacosx-version-min=26.0 -framework IOKit -framework CoreFoundation -o hidrate hidrate.c
#include <IOKit/hid/IOHIDManager.h>
#include <CoreFoundation/CoreFoundation.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <string.h>

static uint8_t bufs[16][1024];
static int nbuf = 0;
static long count = 0;
static uint8_t first[16];
static CFIndex firstLen = 0;
static time_t idleSince = 0;
static int verbose = 0;
static double lastRep = 0;

static void stamp(time_t t, char *out) { strftime(out, 16, "%H:%M:%S", localtime(&t)); }

static void onReport(void *ctx, IOReturn res, void *sender, IOHIDReportType type,
                     uint32_t reportID, uint8_t *report, CFIndex len) {
    if (count == 0) { firstLen = len < 16 ? len : 16; for (CFIndex i = 0; i < firstLen; i++) first[i] = report[i]; }
    count++;
    if (verbose) {
        struct timespec ts; clock_gettime(CLOCK_REALTIME, &ts);
        double t = ts.tv_sec + ts.tv_nsec / 1e9;
        char hm[16]; time_t sec = ts.tv_sec; strftime(hm, sizeof hm, "%H:%M:%S", localtime(&sec));
        printf("%s.%03ld +%6.1f :", hm, ts.tv_nsec / 1000000, lastRep ? (t - lastRep) * 1000 : 0.0);
        for (CFIndex i = 0; i < len && i < 32; i++) printf(" %02x", report[i]);
        printf("\n"); fflush(stdout);
        lastRep = t;
    }
}

static void onTick(CFRunLoopTimerRef timer, void *info) {
    time_t t = time(NULL); char ts[16]; stamp(t - 1, ts);
    if (count > 0) {
        if (idleSince) { char a[16]; stamp(idleSince, a); printf("%s .. %s idle\n", a, ts); idleSince = 0; }
        printf("%s n=%ld :", ts, count);
        for (CFIndex i = 0; i < firstLen; i++) printf(" %02x", first[i]);
        printf("\n"); fflush(stdout);
        count = 0;
    } else if (!idleSince) {
        idleSince = t - 1;
    }
}

static void onMatch(void *ctx, IOReturn res, void *sender, IOHIDDeviceRef dev) {
    if (nbuf >= 16) return;
    CFStringRef prod = IOHIDDeviceGetProperty(dev, CFSTR(kIOHIDProductKey));
    char name[128] = "?"; if (prod) CFStringGetCString(prod, name, sizeof name, kCFStringEncodingUTF8);
    printf("matched: %s\n", name); fflush(stdout);
    IOHIDDeviceRegisterInputReportCallback(dev, bufs[nbuf], sizeof bufs[nbuf], onReport, NULL);
    nbuf++;
}

int main(int argc, char **argv) {
    if (argc < 2) { fprintf(stderr, "usage: %s <vendorID-hex> [seconds]\n", argv[0]); return 1; }
    int vid = (int)strtol(argv[1], NULL, 16);
    double secs = argc > 2 ? atof(argv[2]) : 3600;
    verbose = argc > 3 && !strcmp(argv[3], "-v");
    IOHIDManagerRef m = IOHIDManagerCreate(kCFAllocatorDefault, kIOHIDOptionsTypeNone);
    CFNumberRef v = CFNumberCreate(NULL, kCFNumberIntType, &vid);
    const void *k[] = { CFSTR(kIOHIDVendorIDKey) }; const void *vals[] = { v };
    CFDictionaryRef match = CFDictionaryCreate(NULL, k, vals, 1, &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
    IOHIDManagerSetDeviceMatching(m, match);
    IOHIDManagerRegisterDeviceMatchingCallback(m, onMatch, NULL);
    IOHIDManagerScheduleWithRunLoop(m, CFRunLoopGetCurrent(), kCFRunLoopDefaultMode);
    IOReturn r = IOHIDManagerOpen(m, kIOHIDOptionsTypeNone);
    if (r != kIOReturnSuccess) { fprintf(stderr, "IOHIDManagerOpen failed 0x%x\n", r); return 1; }
    CFRunLoopTimerRef tm = CFRunLoopTimerCreate(NULL, CFAbsoluteTimeGetCurrent() + 1, 1, 0, 0, onTick, NULL);
    CFRunLoopAddTimer(CFRunLoopGetCurrent(), tm, kCFRunLoopDefaultMode);
    CFRunLoopRunInMode(kCFRunLoopDefaultMode, secs, false);
    onTick(NULL, NULL);
    return 0;
}
