/*
 * libdrm_lease_shim.so — LD_PRELOAD shim for DRM lease fd injection
 *
 * mpv --vo=drm calls open("/dev/dri/card1") internally.  That creates a fresh
 * drm_file with no lease context, so two concurrent mpv processes compete for
 * DRM master and only one wins.
 *
 * This shim intercepts every open() / open64() / openat() for a /dev/dri/
 * path and returns dup(DRM_LEASE_FD) instead.  dup() shares the same
 * underlying struct file * (same drm_file, same lease), so all DRM ioctls on
 * the returned fd use the lease — giving each mpv exclusive master over its
 * own CRTC/connector/plane without interfering with the other.
 *
 * Usage: set DRM_LEASE_FD=<fd> and LD_PRELOAD=<path>/libdrm_lease_shim.so
 * before exec-ing mpv.  The lease fd must be inherited by the child process.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static int (*real_open)(const char *, int, ...)    = NULL;
static int (*real_openat)(int, const char *, int, ...) = NULL;
static int lease_fd = -1;

__attribute__((constructor))
static void shim_init(void) {
    real_open   = dlsym(RTLD_NEXT, "open");
    real_openat = dlsym(RTLD_NEXT, "openat");
    const char *s = getenv("DRM_LEASE_FD");
    if (s && *s)
        lease_fd = atoi(s);
}

static int is_dri(const char *path) {
    return path && lease_fd >= 0 && strstr(path, "/dev/dri/") != NULL;
}

int open(const char *path, int flags, ...) {
    if (is_dri(path))
        return dup(lease_fd);
    va_list ap; va_start(ap, flags);
    mode_t mode = va_arg(ap, mode_t); va_end(ap);
    return real_open ? real_open(path, flags, mode) : -1;
}

/* open64 is an alias on 64-bit; intercept for completeness */
int open64(const char *path, int flags, ...) {
    if (is_dri(path))
        return dup(lease_fd);
    va_list ap; va_start(ap, flags);
    mode_t mode = va_arg(ap, mode_t); va_end(ap);
    return real_open ? real_open(path, flags, mode) : -1;
}

int openat(int dirfd, const char *path, int flags, ...) {
    if (is_dri(path))
        return dup(lease_fd);
    va_list ap; va_start(ap, flags);
    mode_t mode = va_arg(ap, mode_t); va_end(ap);
    return real_openat ? real_openat(dirfd, path, flags, mode) : -1;
}
