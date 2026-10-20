# SHIVKSU NEXT

Android manager/UI based on Baka-SU/BakaSU v4.2.0-rc3 (239e1e8).
Kernel, shared UAPI, ksud and ksuinit use SukiSU-Ultra v4.2.1 (fd2a851).
The manager native bridge adapts the SukiSU manager-list ioctl. The legacy
single-certificate manager setting is hidden because SukiSU uses a multi-entry list.
Launcher and home page use the SHIVKSU NEXT name. Package: com.shivksu.next.

## Build

Run the Build Manager GitHub Actions workflow. It builds matching LKM modules,
ksuinit, ksud for ARM64 / ARMv7 / x86_64, and repacks them into signed APKs.
After backend compilation, Package SHIVKSU NEXT can rebuild the latest manager
with that backend run ID. This workflow runs assembleRelease and lintRelease,
repackages the daemon into each APK, verifies signatures and writes SHA256SUMS.
Repository secrets: KEYSTORE (base64 JKS), KEY_ALIAS, KEYSTORE_PASSWORD,
KEY_PASSWORD. The release certificate fingerprint is pinned in the kernel;
keep the same signing key for updates. Never commit private signing material.

For the manager alone: cd manager && ./gradlew assembleRelease.
The final usable APK must also be repacked with the matching ksud artifacts.

## Compatibility

SukiSU v4.2.1 GKI LKM build targets: android12-5.10, android13-5.10,
android13-5.15, android14-5.15, android14-6.1, android15-6.6,
android16-6.12, android17-6.18 (ARM64 and x86_64).
These are build targets, not a guarantee for every device. Kernel KMI,
configuration, boot image format and bootloader state must match.
ARMv7 manager support does not provide an ARMv7 GKI LKM.
Magisk, APatch and other root implementations are not interchangeable with
the KernelSU kernel interface. Existing kernels must trust this manager's
signing certificate or explicitly support adding it as a manager.
SukiSU uses one live umount list with save/apply persistence; the manager's
saved-list controls are adapted to that backend behavior.

Upstream licenses and contributor notices are retained in this repository.
