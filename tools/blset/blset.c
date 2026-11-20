// blset: read/write AppleBacklightDisplay IODisplayParameters directly (bypasses CoreBrightness)
// usage: blset                      -> list brightness/bklt/linear-brightness*
//        blset int <param> <value>  -> IODisplaySetIntegerParameter + commit
//        blset float <param> <0..1> -> IODisplaySetFloatParameter + commit
//        blset prop <param> <value> -> IORegistryEntrySetCFProperty(param, number) (raw path)
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <IOKit/IOKitLib.h>
#include <IOKit/graphics/IOGraphicsLib.h>
#include <CoreFoundation/CoreFoundation.h>

static void show(io_service_t s, const char *name) {
    CFStringRef k = CFStringCreateWithCString(NULL, name, kCFStringEncodingUTF8);
    SInt32 v = 0, mn = 0, mx = 0; float f = 0;
    IOReturn r = IODisplayGetIntegerRangeParameter(s, kNilOptions, k, &v, &mn, &mx);
    IOReturn rf = IODisplayGetFloatParameter(s, kNilOptions, k, &f);
    if (r == kIOReturnSuccess) printf("  %-24s value=%d min=%d max=%d float=%.4f\n", name, v, mn, mx, rf ? -1.0f : f);
    else printf("  %-24s (err 0x%x)\n", name, r);
    CFRelease(k);
}

int main(int argc, char **argv) {
    io_iterator_t it;
    if (IOServiceGetMatchingServices(kIOMainPortDefault, IOServiceMatching("AppleBacklightDisplay"), &it)) { puts("match failed"); return 1; }
    io_service_t s = IOIteratorNext(it);
    if (!s) { puts("no AppleBacklightDisplay"); return 1; }
    const char *names[] = {"brightness", "bklt", "linear-brightness", "linear-brightness-probe", "brightness-probe", "commit", NULL};
    if (argc >= 4) {
        CFStringRef k = CFStringCreateWithCString(NULL, argv[2], kCFStringEncodingUTF8);
        IOReturn r;
        if (!strcmp(argv[1], "int")) {
            r = IODisplaySetIntegerParameter(s, kNilOptions, k, atoi(argv[3]));
            printf("SetInteger %s=%d -> 0x%x\n", argv[2], atoi(argv[3]), r);
        } else if (!strcmp(argv[1], "float")) {
            r = IODisplaySetFloatParameter(s, kNilOptions, k, atof(argv[3]));
            printf("SetFloat %s=%f -> 0x%x\n", argv[2], atof(argv[3]), r);
        } else if (!strcmp(argv[1], "prop")) {
            int n = atoi(argv[3]);
            CFNumberRef num = CFNumberCreate(NULL, kCFNumberIntType, &n);
            r = IORegistryEntrySetCFProperty(s, k, num);
            printf("SetCFProperty %s=%d -> 0x%x\n", argv[2], n, r);
        } else { puts("bad mode"); return 1; }
        if (strcmp(argv[1], "prop")) printf("Commit -> 0x%x\n", IODisplayCommitParameters(s, kNilOptions));
    }
    puts("AppleBacklightDisplay params:");
    for (int i = 0; names[i]; i++) show(s, names[i]);
    return 0;
}
