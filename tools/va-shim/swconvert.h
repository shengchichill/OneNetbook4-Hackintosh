#pragma once
#include <IOSurface/IOSurface.h>
#include <stddef.h>

// rects are {x, y, w, h} as passed by AppleGVA; returns 0 when dst was written, -1 otherwise (reason in why)
int vashim_convert(IOSurfaceRef src, const double srcRect[4], IOSurfaceRef dst, const double dstRect[4], char *why, size_t n);
