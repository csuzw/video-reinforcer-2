"""
DRM lease management for dual-HDMI output on Raspberry Pi 5.

Creates isolated DRM leases so two mpv processes can each hold DRM master
for their own CRTC/connector/plane without competing.  Only the primary
plane is included in each lease; the shared overlay plane (107) is excluded
so mpv falls back to software rendering on the primary plane.
"""
import ctypes
import ctypes.util
import logging
import os
from typing import Dict, Optional, Tuple

log = logging.getLogger(__name__)

_DRM_MODE_CONNECTOR_HDMIA = 11
_DRM_MODE_OBJECT_PLANE = 0xeeeeeeee
_DRM_PLANE_TYPE_PRIMARY = 1
_DRM_CARD = "/dev/dri/card1"


# ---------------------------------------------------------------------------
# libdrm struct mirrors (64-bit AArch64 layout, natural alignment)
# ---------------------------------------------------------------------------

class _Res(ctypes.Structure):
    _fields_ = [
        ("count_fbs",        ctypes.c_int),
        ("fbs",              ctypes.POINTER(ctypes.c_uint32)),
        ("count_crtcs",      ctypes.c_int),
        ("crtcs",            ctypes.POINTER(ctypes.c_uint32)),
        ("count_connectors", ctypes.c_int),
        ("connectors",       ctypes.POINTER(ctypes.c_uint32)),
        ("count_encoders",   ctypes.c_int),
        ("encoders",         ctypes.POINTER(ctypes.c_uint32)),
        ("min_width",        ctypes.c_uint32),
        ("max_width",        ctypes.c_uint32),
        ("min_height",       ctypes.c_uint32),
        ("max_height",       ctypes.c_uint32),
    ]


class _Connector(ctypes.Structure):
    _fields_ = [
        ("connector_id",      ctypes.c_uint32),
        ("encoder_id",        ctypes.c_uint32),
        ("connector_type",    ctypes.c_uint32),
        ("connector_type_id", ctypes.c_uint32),
        ("connection",        ctypes.c_uint32),
        ("mmWidth",           ctypes.c_uint32),
        ("mmHeight",          ctypes.c_uint32),
        ("subpixel",          ctypes.c_uint32),
        ("count_modes",       ctypes.c_int),
        ("modes",             ctypes.c_void_p),
        ("count_props",       ctypes.c_int),
        ("props",             ctypes.POINTER(ctypes.c_uint32)),
        ("prop_values",       ctypes.POINTER(ctypes.c_uint64)),
        ("count_encoders",    ctypes.c_int),
        ("encoders",          ctypes.POINTER(ctypes.c_uint32)),
    ]


class _Encoder(ctypes.Structure):
    _fields_ = [
        ("encoder_id",      ctypes.c_uint32),
        ("encoder_type",    ctypes.c_uint32),
        ("crtc_id",         ctypes.c_uint32),
        ("possible_crtcs",  ctypes.c_uint32),
        ("possible_clones", ctypes.c_uint32),
    ]


class _PlaneRes(ctypes.Structure):
    _fields_ = [
        ("count_planes", ctypes.c_uint32),
        ("planes",       ctypes.POINTER(ctypes.c_uint32)),
    ]


class _Plane(ctypes.Structure):
    _fields_ = [
        ("count_formats",  ctypes.c_uint32),
        ("formats",        ctypes.POINTER(ctypes.c_uint32)),
        ("plane_id",       ctypes.c_uint32),
        ("crtc_id",        ctypes.c_uint32),
        ("fb_id",          ctypes.c_uint32),
        ("crtc_x",         ctypes.c_uint32),
        ("crtc_y",         ctypes.c_uint32),
        ("x",              ctypes.c_uint32),
        ("y",              ctypes.c_uint32),
        ("possible_crtcs", ctypes.c_uint32),
        ("gamma_size",     ctypes.c_uint32),
    ]


class _ObjProps(ctypes.Structure):
    _fields_ = [
        ("count_props", ctypes.c_uint32),
        ("props",       ctypes.POINTER(ctypes.c_uint32)),
        ("prop_values", ctypes.POINTER(ctypes.c_uint64)),
    ]


class _Prop(ctypes.Structure):
    _fields_ = [
        ("prop_id",      ctypes.c_uint32),
        ("flags",        ctypes.c_uint32),
        ("name",         ctypes.c_char * 32),
        ("count_values", ctypes.c_int),
        ("values",       ctypes.POINTER(ctypes.c_uint64)),
        ("count_enums",  ctypes.c_int),
        ("enums",        ctypes.c_void_p),
        ("count_blobs",  ctypes.c_int),
        ("blob_ids",     ctypes.POINTER(ctypes.c_uint32)),
    ]


def _load_libdrm():
    name = ctypes.util.find_library("drm")
    lib = ctypes.CDLL(name or "libdrm.so.2", use_errno=True)

    lib.drmModeGetResources.restype = ctypes.POINTER(_Res)
    lib.drmModeGetResources.argtypes = [ctypes.c_int]
    lib.drmModeFreeResources.argtypes = [ctypes.POINTER(_Res)]

    lib.drmModeGetConnector.restype = ctypes.POINTER(_Connector)
    lib.drmModeGetConnector.argtypes = [ctypes.c_int, ctypes.c_uint32]
    lib.drmModeFreeConnector.argtypes = [ctypes.POINTER(_Connector)]

    lib.drmModeGetEncoder.restype = ctypes.POINTER(_Encoder)
    lib.drmModeGetEncoder.argtypes = [ctypes.c_int, ctypes.c_uint32]
    lib.drmModeFreeEncoder.argtypes = [ctypes.POINTER(_Encoder)]

    lib.drmModeGetPlaneResources.restype = ctypes.POINTER(_PlaneRes)
    lib.drmModeGetPlaneResources.argtypes = [ctypes.c_int]
    lib.drmModeFreePlaneResources.argtypes = [ctypes.POINTER(_PlaneRes)]

    lib.drmModeGetPlane.restype = ctypes.POINTER(_Plane)
    lib.drmModeGetPlane.argtypes = [ctypes.c_int, ctypes.c_uint32]
    lib.drmModeFreePlane.argtypes = [ctypes.POINTER(_Plane)]

    lib.drmModeObjectGetProperties.restype = ctypes.POINTER(_ObjProps)
    lib.drmModeObjectGetProperties.argtypes = [ctypes.c_int, ctypes.c_uint32, ctypes.c_uint32]
    lib.drmModeFreeObjectProperties.argtypes = [ctypes.POINTER(_ObjProps)]

    lib.drmModeGetProperty.restype = ctypes.POINTER(_Prop)
    lib.drmModeGetProperty.argtypes = [ctypes.c_int, ctypes.c_uint32]
    lib.drmModeFreeProperty.argtypes = [ctypes.POINTER(_Prop)]

    lib.drmModeCreateLease.restype = ctypes.c_int
    lib.drmModeCreateLease.argtypes = [
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.c_int,
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_uint32),
    ]
    lib.drmSetMaster.restype = ctypes.c_int
    lib.drmSetMaster.argtypes = [ctypes.c_int]
    lib.drmDropMaster.restype = ctypes.c_int
    lib.drmDropMaster.argtypes = [ctypes.c_int]
    lib.drmSetClientCap.restype = ctypes.c_int
    lib.drmSetClientCap.argtypes = [ctypes.c_int, ctypes.c_uint64, ctypes.c_uint64]

    return lib


def _plane_type(lib, fd: int, plane_id: int) -> Optional[int]:
    obj_props = lib.drmModeObjectGetProperties(fd, plane_id, _DRM_MODE_OBJECT_PLANE)
    if not obj_props:
        return None
    try:
        for i in range(obj_props.contents.count_props):
            prop_id = obj_props.contents.props[i]
            val = int(obj_props.contents.prop_values[i])
            prop = lib.drmModeGetProperty(fd, prop_id)
            if not prop:
                continue
            try:
                if prop.contents.name == b"type":
                    return val
            finally:
                lib.drmModeFreeProperty(prop)
    finally:
        lib.drmModeFreeObjectProperties(obj_props)
    return None


def _crtc_for_connector(lib, fd: int, conn, crtc_ids, used_crtcs: set) -> Optional[int]:
    """Return a CRTC id for this connector, preferring its active encoder."""
    # Active encoder path
    if conn.encoder_id:
        enc = lib.drmModeGetEncoder(fd, conn.encoder_id)
        if enc:
            crtc_id = enc.contents.crtc_id
            lib.drmModeFreeEncoder(enc)
            if crtc_id and crtc_id not in used_crtcs:
                return crtc_id

    # Fallback: walk possible_encoders → possible_crtcs
    for i in range(conn.count_encoders):
        enc = lib.drmModeGetEncoder(fd, conn.encoders[i])
        if not enc:
            continue
        possible = enc.contents.possible_crtcs
        lib.drmModeFreeEncoder(enc)
        for idx, cid in enumerate(crtc_ids):
            if (possible & (1 << idx)) and cid not in used_crtcs:
                return cid
    return None


def create_leases(drm_card: str = _DRM_CARD) -> Tuple[int, Dict[int, int]]:
    """
    Open *drm_card* as DRM master, partition it into per-monitor leases, and
    return ``(grantor_fd, {monitor_number: lease_fd})``.

    The caller must keep *grantor_fd* open for the lifetime of the mpv
    processes.  Raises ``RuntimeError`` on failure; callers should fall back
    to starting mpv without leases.
    """
    lib = _load_libdrm()

    fd = os.open(drm_card, os.O_RDWR)
    if lib.drmSetMaster(fd) != 0:
        os.close(fd)
        raise RuntimeError(f"Cannot become DRM master on {drm_card}")

    # Required to see primary and cursor planes (not just overlays)
    _DRM_CLIENT_CAP_UNIVERSAL_PLANES = 2
    if lib.drmSetClientCap(fd, _DRM_CLIENT_CAP_UNIVERSAL_PLANES, 1) != 0:
        log.warning("DRM_CLIENT_CAP_UNIVERSAL_PLANES not supported — primary planes may not be found")

    res = lib.drmModeGetResources(fd)
    if not res:
        os.close(fd)
        raise RuntimeError("drmModeGetResources failed")

    n_crtcs = res.contents.count_crtcs
    crtc_ids = [res.contents.crtcs[i] for i in range(n_crtcs)]

    # Map HDMI-A type_id (1, 2, …) → (connector_id, crtc_id)
    monitor_info: Dict[int, Tuple[int, int]] = {}
    used_crtcs: set = set()

    for i in range(res.contents.count_connectors):
        conn_id = res.contents.connectors[i]
        conn = lib.drmModeGetConnector(fd, conn_id)
        if not conn:
            continue
        try:
            c = conn.contents
            if c.connector_type != _DRM_MODE_CONNECTOR_HDMIA:
                continue
            type_id = c.connector_type_id  # 1 = HDMI-A-1, 2 = HDMI-A-2
            crtc_id = _crtc_for_connector(lib, fd, c, crtc_ids, used_crtcs)
            if crtc_id:
                monitor_info[type_id] = (conn_id, crtc_id)
                used_crtcs.add(crtc_id)
                log.debug("HDMI-A-%d: connector=%d crtc=%d", type_id, conn_id, crtc_id)
            else:
                log.warning("HDMI-A-%d (connector %d): no available CRTC", type_id, conn_id)
        finally:
            lib.drmModeFreeConnector(conn)

    lib.drmModeFreeResources(res)

    if not monitor_info:
        os.close(fd)
        raise RuntimeError("No HDMI-A connectors found")

    # Find primary plane for each CRTC
    crtc_primary: Dict[int, int] = {}
    plane_res = lib.drmModeGetPlaneResources(fd)
    if plane_res:
        for i in range(plane_res.contents.count_planes):
            plane_id = plane_res.contents.planes[i]
            plane = lib.drmModeGetPlane(fd, plane_id)
            if not plane:
                continue
            try:
                p = plane.contents
                if _plane_type(lib, fd, plane_id) != _DRM_PLANE_TYPE_PRIMARY:
                    continue
                for idx, cid in enumerate(crtc_ids):
                    if (p.possible_crtcs & (1 << idx)) and cid not in crtc_primary:
                        crtc_primary[cid] = plane_id
                        log.debug("CRTC %d: primary plane %d", cid, plane_id)
            finally:
                lib.drmModeFreePlane(plane)
        lib.drmModeFreePlaneResources(plane_res)

    # Create one lease per monitor
    lease_fds: Dict[int, int] = {}
    lessee_id = ctypes.c_uint32(0)

    for monitor_num, (conn_id, crtc_id) in sorted(monitor_info.items()):
        objects = [crtc_id, conn_id]
        if crtc_id in crtc_primary:
            objects.append(crtc_primary[crtc_id])
        arr = (ctypes.c_uint32 * len(objects))(*objects)
        lease_fd = lib.drmModeCreateLease(fd, arr, len(objects), 0, ctypes.byref(lessee_id))
        if lease_fd < 0:
            for efd in lease_fds.values():
                os.close(efd)
            os.close(fd)
            raise RuntimeError(
                f"drmModeCreateLease failed for monitor {monitor_num} "
                f"(errno {ctypes.get_errno()})"
            )
        lease_fds[monitor_num] = lease_fd
        log.info("Monitor %d: DRM lease fd=%d objects=%s", monitor_num, lease_fd, objects)

    lib.drmDropMaster(fd)
    return fd, lease_fds
