// imgdump — dump a dyld-shared-cache image from memory, for static analysis on another machine.
// Build (Mac): clang -arch x86_64 -mmacosx-version-min=26.0 -O1 -o imgdump imgdump.c
// Usage:  imgdump dump <image path> <out prefix>   → <prefix>.<SEG> raw segment bytes, <prefix>.segs, <prefix>.syms
//         imgdump lookup <image path> <unslid hex addr>...  → dladdr() for each address (names call targets in other dylibs)
//         imgdump ptr <image path> <unslid hex addr>...     → like lookup, for the pointer stored at each address (GOT slot)
//         imgdump str <image path> <unslid hex addr>...     → C string at each address (all cache images share one slide)
// Addresses in all outputs are unslid (as in the cache), so they match each other across runs.
#include <dlfcn.h>
#include <mach-o/dyld.h>
#include <mach-o/loader.h>
#include <mach-o/nlist.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static const struct mach_header_64 *find_image(const char *path, intptr_t *slide) {
    for (uint32_t i = 0; i < _dyld_image_count(); i++) {
        const char *n = _dyld_get_image_name(i);
        if (n && strcmp(n, path) == 0) {
            *slide = _dyld_get_image_vmaddr_slide(i);
            return (const struct mach_header_64 *)_dyld_get_image_header(i);
        }
    }
    return NULL;
}

int main(int argc, char **argv) {
    if (argc < 4) { fprintf(stderr, "usage: %s dump <image> <prefix> | lookup <image> <addr>...\n", argv[0]); return 2; }
    if (!dlopen(argv[2], RTLD_NOW | RTLD_GLOBAL)) { fprintf(stderr, "dlopen: %s\n", dlerror()); return 1; }
    intptr_t slide = 0;
    const struct mach_header_64 *mh = find_image(argv[2], &slide);
    if (!mh) { fprintf(stderr, "image not found after dlopen\n"); return 1; }

    if (strcmp(argv[1], "str") == 0) {  // C strings at unslid addresses (cfstring payloads live in other images)
        for (int i = 3; i < argc; i++) {
            uint64_t a = strtoull(argv[i], NULL, 16);
            printf("%llx \"%s\"\n", (unsigned long long)a, (const char *)(a + slide));
        }
        return 0;
    }
    int deref = strcmp(argv[1], "ptr") == 0;  // ptr: read the pointer stored at each address (a GOT slot), then dladdr it
    if (deref || strcmp(argv[1], "lookup") == 0) {
        for (int i = 3; i < argc; i++) {
            uint64_t a = strtoull(argv[i], NULL, 16);
            if (deref) { printf("%llx -> ", (unsigned long long)a); a = *(const uint64_t *)(a + slide) - slide; }
            Dl_info di;
            if (dladdr((void *)(a + slide), &di) && di.dli_sname)
                printf("%llx %s+0x%llx (%s)\n", (unsigned long long)a, di.dli_sname,
                       (unsigned long long)(a + slide - (uint64_t)di.dli_saddr), di.dli_fname);
            else
                printf("%llx ? (%s)\n", (unsigned long long)a, di.dli_fname ? di.dli_fname : "-");
        }
        return 0;
    }

    char fn[1024];
    snprintf(fn, sizeof fn, "%s.segs", argv[3]);
    FILE *segs = fopen(fn, "w");
    const struct load_command *lc = (const void *)(mh + 1);
    const struct symtab_command *st = NULL;
    uint64_t le_vm = 0, le_off = 0;
    for (uint32_t i = 0; i < mh->ncmds; i++, lc = (const void *)((const char *)lc + lc->cmdsize)) {
        if (lc->cmd == LC_SEGMENT_64) {
            const struct segment_command_64 *sg = (const void *)lc;
            fprintf(segs, "%-16s vm 0x%llx size 0x%llx fileoff 0x%llx\n", sg->segname,
                    (unsigned long long)sg->vmaddr, (unsigned long long)sg->vmsize, (unsigned long long)sg->fileoff);
            const struct section_64 *sc = (const void *)(sg + 1);
            for (uint32_t j = 0; j < sg->nsects; j++)
                fprintf(segs, "    %-16s 0x%llx size 0x%llx\n", sc[j].sectname,
                        (unsigned long long)sc[j].addr, (unsigned long long)sc[j].size);
            if (strcmp(sg->segname, "__LINKEDIT") == 0) { le_vm = sg->vmaddr; le_off = sg->fileoff; continue; }
            snprintf(fn, sizeof fn, "%s.%s", argv[3], sg->segname);
            FILE *f = fopen(fn, "wb");
            fwrite((const void *)(sg->vmaddr + slide), 1, sg->vmsize, f);
            fclose(f);
        } else if (lc->cmd == LC_SYMTAB) {
            st = (const void *)lc;
        }
    }
    fclose(segs);
    if (st && le_vm) {
        // In the shared cache, symoff/stroff are offsets into the shared __LINKEDIT, relative to its fileoff.
        const struct nlist_64 *nl = (const void *)(le_vm + slide + st->symoff - le_off);
        const char *strs = (const char *)(le_vm + slide + st->stroff - le_off);
        snprintf(fn, sizeof fn, "%s.syms", argv[3]);
        FILE *f = fopen(fn, "w");
        for (uint32_t i = 0; i < st->nsyms; i++)
            if ((nl[i].n_type & N_TYPE) == N_SECT && nl[i].n_value)
                fprintf(f, "%llx %s\n", (unsigned long long)nl[i].n_value, strs + nl[i].n_un.n_strx);
        fclose(f);
    }
    printf("slide 0x%lx, done\n", (long)slide);
    return 0;
}
