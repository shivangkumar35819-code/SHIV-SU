The Android manager and UI originate from Baka-SU/BakaSU tag v4.2.0-rc3,
commit 239e1e8. The kernel, userspace, Cargo workspace and shared UAPI originate
from SukiSU-Ultra/SukiSU-Ultra tag v4.2.1, commit fd2a851. Original licenses
and copyright notices are retained.

Local changes: SHIVKSU NEXT display name and package, release signing identity,
native manager-list ioctl adapter, manager compatibility headers, and build
workflow integration. Prebuilt upstream LKM binaries are not re-signed or
patched: modules are built from the tagged source with this manager's public
certificate identity, so the kernel can authenticate the newly signed APK.

GKI LKM targets are provided by the upstream DDK build matrix. This does not
produce device-specific boot.img files or establish hardware compatibility.
