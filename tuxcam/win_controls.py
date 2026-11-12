"""Windows camera controls via DirectShow COM.

Queries IAMVideoProcAmp (brightness, contrast, white balance, gain…) and
IAMCameraControl (exposure, focus, zoom, pan/tilt…) on a second binding of
the camera's moniker — the same trick v4l2.py uses on Linux, where control
ioctls work on a separate open of the device while GStreamer streams.
UVC drivers route property-set requests through the driver stack, so this
works mid-stream on standard cameras.

Same API as v4l2.py: list_controls(path) / get_ctrl(path, id) /
set_ctrl(path, id, value), where `path` is the PnP symbolic path reported
by Gst.DeviceMonitor (\\\\?\\usb#vid_....#{guid}).
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

import comtypes
from comtypes import COMMETHOD, GUID, HRESULT, IUnknown, POINTER

from .ctrls import (  # noqa: F401  (T_*/FLAG_* re-exported — same API as v4l2)
    Ctrl,
    FLAG_DISABLED,
    FLAG_READ_ONLY,
    FLAG_WRITE_ONLY,
    FLAG_GRABBED,
    NEXT_CTRL,
    T_INT,
    T_BOOL,
    T_MENU,
    T_BUTTON,
    T_CLASS,
    T_INT_MENU,
)

CLSID_SystemDeviceEnum = GUID("{62BE5D10-60EB-11D0-BD3B-00A0C911CE86}")
CLSID_VideoInputDeviceCategory = GUID(
    "{860BB310-5D01-11d0-BD3B-00A0C911CE86}"
)


class IBindCtx(IUnknown):
    _iid_ = GUID("{0000000E-0000-0000-C000-000000000046}")


class IPersist(IUnknown):
    _iid_ = GUID("{0000010C-0000-0000-C000-000000000046}")
    _methods_ = [
        COMMETHOD([], HRESULT, "GetClassID",
                  (["out"], POINTER(GUID), "pClassID")),
    ]


class IStream(IUnknown):
    _iid_ = GUID("{0000000C-0000-0000-C000-000000000046}")


class IPersistStream(IPersist):
    _iid_ = GUID("{00000109-0000-0000-C000-000000000046}")
    _methods_ = [
        COMMETHOD([], HRESULT, "IsDirty"),
        COMMETHOD([], HRESULT, "Load", (["in"], POINTER(IStream), "pStm")),
        COMMETHOD([], HRESULT, "Save",
                  (["in"], POINTER(IStream), "pStm"),
                  (["in"], wintypes.BOOL, "fClearDirty")),
        COMMETHOD([], HRESULT, "GetSizeMax",
                  (["out"], POINTER(ctypes.c_uint64), "pcbSize")),
    ]


class IMoniker(IPersistStream):
    _iid_ = GUID("{0000000F-0000-0000-C000-000000000046}")
    _methods_ = [
        COMMETHOD([], HRESULT, "BindToObject",
                  (["in"], POINTER(IBindCtx), "pbc"),
                  (["in"], POINTER("IMoniker"), "pmkToLeft"),
                  (["in"], POINTER(GUID), "riidResult"),
                  (["out"], POINTER(POINTER(IUnknown)), "ppvResult")),
        COMMETHOD([], HRESULT, "BindToStorage",
                  (["in"], POINTER(IBindCtx), "pbc"),
                  (["in"], POINTER("IMoniker"), "pmkToLeft"),
                  (["in"], POINTER(GUID), "riid"),
                  (["out"], POINTER(POINTER(IUnknown)), "ppvObj")),
        COMMETHOD([], HRESULT, "Reduce",
                  (["in"], POINTER(IBindCtx), "pbc"),
                  (["in"], wintypes.DWORD, "dwReduceHowFar"),
                  (["in", "out"], POINTER(POINTER(IUnknown)), "ppmkToLeft"),
                  (["out"], POINTER(POINTER(IUnknown)), "ppmkReduced")),
        COMMETHOD([], HRESULT, "ComposeWith",
                  (["in"], POINTER(IBindCtx), "pbc"),
                  (["in"], POINTER("IMoniker"), "pmkRight"),
                  (["in"], wintypes.BOOL, "fGeneric"),
                  (["out"], POINTER(POINTER(IUnknown)), "ppmkComposite")),
        COMMETHOD([], HRESULT, "Enum",
                  (["in"], POINTER(IBindCtx), "pbc"),
                  (["in"], wintypes.BOOL, "fForward"),
                  (["out"], POINTER(POINTER(IUnknown)), "ppenumMoniker")),
        COMMETHOD([], HRESULT, "IsEqual",
                  (["in"], POINTER("IMoniker"), "pmkOtherMoniker")),
        COMMETHOD([], HRESULT, "Hash",
                  (["out"], POINTER(wintypes.DWORD), "pdwHash")),
        COMMETHOD([], HRESULT, "IsRunning",
                  (["in"], POINTER(IBindCtx), "pbc"),
                  (["in"], POINTER("IMoniker"), "pmkToLeft"),
                  (["in"], POINTER("IMoniker"), "pmkNewlyRunning")),
        COMMETHOD([], HRESULT, "GetTimeOfLastChange",
                  (["in"], POINTER(IBindCtx), "pbc"),
                  (["in"], POINTER("IMoniker"), "pmkToLeft"),
                  (["out"], POINTER(wintypes.FILETIME), "pFileTime")),
        COMMETHOD([], HRESULT, "Inverse",
                  (["out"], POINTER(POINTER(IUnknown)), "ppmk")),
        COMMETHOD([], HRESULT, "CommonPrefixWith",
                  (["in"], POINTER("IMoniker"), "pmkOther"),
                  (["out"], POINTER(POINTER(IUnknown)), "ppmkPrefix")),
        COMMETHOD([], HRESULT, "RelativePathTo",
                  (["in"], POINTER("IMoniker"), "pmkOther"),
                  (["out"], POINTER(POINTER(IUnknown)), "ppmkRelPath")),
        COMMETHOD([], HRESULT, "GetDisplayName",
                  (["in"], POINTER(IBindCtx), "pbc"),
                  (["in"], POINTER("IMoniker"), "pmkToLeft"),
                  (["out"], POINTER(wintypes.LPWSTR), "ppszDisplayName")),
        COMMETHOD([], HRESULT, "ParseDisplayName",
                  (["in"], POINTER(IBindCtx), "pbc"),
                  (["in"], POINTER("IMoniker"), "pmkToLeft"),
                  (["in"], wintypes.LPCWSTR, "pszDisplayName"),
                  (["out"], POINTER(wintypes.ULONG), "pchEaten"),
                  (["out"], POINTER(POINTER(IUnknown)), "ppmkOut")),
        COMMETHOD([], HRESULT, "IsSystemMoniker",
                  (["out"], POINTER(wintypes.DWORD), "pdwMksys")),
    ]


class IEnumMoniker(IUnknown):
    _iid_ = GUID("{00000102-0000-0000-C000-000000000046}")
    _methods_ = [
        COMMETHOD([], HRESULT, "Next",
                  (["in"], wintypes.ULONG, "celt"),
                  (["out"], POINTER(POINTER(IMoniker)), "rgelt"),
                  (["out"], POINTER(wintypes.ULONG), "pceltFetched")),
        COMMETHOD([], HRESULT, "Skip", (["in"], wintypes.ULONG, "celt")),
        COMMETHOD([], HRESULT, "Reset"),
        COMMETHOD([], HRESULT, "Clone",
                  (["out"], POINTER(POINTER(IUnknown)), "ppenum")),
    ]


class ICreateDevEnum(IUnknown):
    _iid_ = GUID("{29840822-5B84-11D0-BD3B-00A0C911CE86}")
    _methods_ = [
        COMMETHOD([], HRESULT, "CreateClassEnumerator",
                  (["in"], POINTER(GUID), "clsDeviceClass"),
                  (["out"], POINTER(POINTER(IEnumMoniker)), "ppEnumMoniker"),
                  (["in"], wintypes.DWORD, "dwFlags")),
    ]


class IBaseFilter(IUnknown):
    _iid_ = GUID("{56A86895-0AD4-11CE-B03A-0020AF0BA770}")


def _range_iface(iid):
    """IAMVideoProcAmp / IAMCameraControl share the same 3 methods."""

    class _Range(IUnknown):
        _iid_ = GUID(iid)
        _methods_ = [
            COMMETHOD([], HRESULT, "GetRange",
                      (["in"], wintypes.LONG, "Property"),
                      (["out"], POINTER(wintypes.LONG), "pMin"),
                      (["out"], POINTER(wintypes.LONG), "pMax"),
                      (["out"], POINTER(wintypes.LONG), "pSteppingDelta"),
                      (["out"], POINTER(wintypes.LONG), "pDefault"),
                      (["out"], POINTER(wintypes.LONG), "pCapsFlags")),
            COMMETHOD([], HRESULT, "Set",
                      (["in"], wintypes.LONG, "Property"),
                      (["in"], wintypes.LONG, "lValue"),
                      (["in"], wintypes.LONG, "Flags")),
            COMMETHOD([], HRESULT, "Get",
                      (["in"], wintypes.LONG, "Property"),
                      (["out"], POINTER(wintypes.LONG), "lValue"),
                      (["out"], POINTER(wintypes.LONG), "Flags")),
        ]

    return _Range


IAMVideoProcAmp = _range_iface("{C6E13360-30AC-11d0-A18C-00A0C9118956}")
IAMVideoProcAmp.__name__ = "IAMVideoProcAmp"
IAMCameraControl = _range_iface("{C6E13370-30AC-11d0-A18C-00A0C9118956}")
IAMCameraControl.__name__ = "IAMCameraControl"

# (property id, display name) — Windows DirectShow enums
_VPA_PROPS = [
    (0, "Brightness"), (1, "Contrast"), (2, "Hue"), (3, "Saturation"),
    (4, "Sharpness"), (5, "Gamma"), (6, "Color Enable"),
    (7, "White Balance"), (8, "Backlight Compensation"), (9, "Gain"),
]
_CC_PROPS = [
    (0, "Pan"), (1, "Tilt"), (2, "Roll"), (3, "Zoom"),
    (4, "Exposure"), (5, "Iris"), (6, "Focus"),
]
# Drivers disagree on flag bits: VideoProcAmp documents Auto=0x10/Manual=0x20
# and CameraControl Auto=0x2/Manual=0x1, but many UVC drivers return 0x1/0x2
# on both. Detect the real bits from the caps value at enumeration time.
_AUTO_BITS = {0: (0x10, 0x1), 1: (0x2, 0x10)}
_MANUAL_BITS = {0: (0x20, 0x2), 1: (0x1, 0x20)}

_FILTERS = {}  # normalized pnp path -> (IBaseFilter, vpa, cc)
_META = {}     # ctrl id -> (iface_idx, prop, auto_bit, manual_bit)


def _norm_path(p: str) -> str:
    p = (p or "").lower().replace("/", "\\")
    for pre in ("@device:pnp:", "\\??\\", "\\\\?\\"):
        if p.startswith(pre):
            p = p[len(pre):]
    i = p.find("#{")  # drop trailing interface-guid (e.g. #{65e8773d-...}\global)
    if i >= 0:
        p = p[:i]
    return p


def _mkid(iface: int, prop: int, auto: bool) -> int:
    return (iface << 16) | (prop << 4) | int(auto)


def _mk_class(name):
    return Ctrl(0, T_CLASS, name, 0, 0, 0, 0, 0)


def _interfaces(path):
    """(videoprocamp, cameracontrol) bound to the camera, either may be None."""
    norm = _norm_path(path)
    hit = _FILTERS.get(norm)
    if hit is None:
        filt = None
        comtypes.CoInitialize()
        devenum = comtypes.CoCreateInstance(
            CLSID_SystemDeviceEnum, interface=ICreateDevEnum
        )
        enum = devenum.CreateClassEnumerator(
            CLSID_VideoInputDeviceCategory, 0
        )
        if enum:
            while True:
                try:
                    res = enum.Next(1)
                except Exception:
                    break
                mk = res[0] if isinstance(res, tuple) else res
                if not mk:
                    break
                try:
                    disp = mk.GetDisplayName(None, None)
                except Exception:
                    continue
                if _norm_path(disp) == norm:
                    filt = mk.BindToObject(None, None, IBaseFilter._iid_)
                    break
        if filt is None:
            hit = (None, None, None)
        else:
            try:
                vpa = filt.QueryInterface(IAMVideoProcAmp)
            except Exception:
                vpa = None
            try:
                cc = filt.QueryInterface(IAMCameraControl)
            except Exception:
                cc = None
            hit = (filt, vpa, cc)
        _FILTERS[norm] = hit
    return hit[1], hit[2]


def _pick_bit(caps: int, cands) -> int:
    for b in cands:
        if caps & b:
            return b
    return 0


def list_controls(path: str) -> list:
    out = []
    for iface_idx, (iface, props, title) in enumerate(
        (
            (_interfaces(path)[0], _VPA_PROPS, "Video Proc Amp"),
            (_interfaces(path)[1], _CC_PROPS, "Camera Control"),
        )
    ):
        if iface is None:
            continue
        group = []
        for prop, name in props:
            try:
                mn, mx, step, dflt, caps = iface.GetRange(prop)
            except Exception:
                continue
            auto_bit = _pick_bit(caps, _AUTO_BITS[iface_idx])
            manual_bit = _pick_bit(caps, _MANUAL_BITS[iface_idx]) or 0x2
            if auto_bit:
                cid = _mkid(iface_idx, prop, True)
                _META[cid] = (iface_idx, prop, auto_bit, manual_bit)
                group.append(
                    Ctrl(cid, T_BOOL, f"{name}, Auto", 0, 1, 1, 1, 0)
                )
            cid = _mkid(iface_idx, prop, False)
            _META[cid] = (iface_idx, prop, auto_bit, manual_bit)
            ctype = T_BOOL if (mn, mx, step) == (0, 1, 1) else T_INT
            group.append(Ctrl(cid, ctype, name, mn, mx, step, dflt, 0))
        if group:
            out.append(_mk_class(title))
            out.extend(group)
    return out


def _meta(cid: int):
    m = _META.get(cid)
    if m:
        return m
    # fallback: decode the id, guess common flag bits
    iface_idx, prop, auto = (cid >> 16) & 0xFF, (cid >> 4) & 0xFFF, cid & 1
    return (iface_idx, prop, _AUTO_BITS[iface_idx][0], _MANUAL_BITS[iface_idx][0])


def get_ctrl(path: str, cid: int):
    iface_idx, prop, auto_bit, _ = _meta(cid)
    iface = _interfaces(path)[iface_idx]
    if iface is None:
        raise OSError("interface unavailable")
    val, flags = iface.Get(prop)
    if cid & 1:
        return 1 if flags & auto_bit else 0
    return val


def set_ctrl(path: str, cid: int, value: int) -> bool:
    iface_idx, prop, auto_bit, manual_bit = _meta(cid)
    iface = _interfaces(path)[iface_idx]
    if iface is None:
        return False
    try:
        if cid & 1:
            cur, _ = iface.Get(prop)
            iface.Set(prop, cur, auto_bit if value else manual_bit)
        else:
            iface.Set(prop, value, manual_bit)
        return True
    except Exception:
        return False
