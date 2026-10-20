SHIVKSU NEXT uses the ReSukiSU/BakaSU v4.2.0-rc3 manager interface with the matching SukiSU-Ultra v4.2.1 kernel, daemon and init backend.

- App launcher and home page: **SHIVKSU NEXT**.
- Package: `com.shivksu.next`.
- Signed release APKs for ARM64, ARMv7, x86_64 and universal installation.
- 16 GKI LKM builds: Android 12–17 KMI targets, ARM64 and x86_64.
- Kernel builds recognize the SHIVKSU NEXT release signing certificate.
- Manager update links, manager-list ioctl and umount commands adapted to this fork.
- Legacy single-certificate manager controls are hidden because the backend uses a different multi-manager API.

Use the ARM64 APK for most modern Android phones, or the universal APK when needed. LKM files must match the device kernel KMI. The ARMv7 APK does not include an ARMv7 GKI LKM. These assets do not include a device-specific boot image.

Build validation covers Gradle release compilation, lint, APK signatures, ABI libraries and LKM certificate fingerprints. Hardware boot/root behavior has not been tested on a phone. This release does not promise support for every device or interchangeable operation with Magisk/APatch.

Private signing material is stored locally and in GitHub Actions secrets; it is not part of the public source or release assets. Keep the same key for future updates.
