"""Verify packaged ABI libraries and LKM signing identity without a phone."""
from pathlib import Path
import argparse
import hashlib
import struct
import zipfile

parser = argparse.ArgumentParser()
parser.add_argument('directory', type=Path)
parser.add_argument('--certificate', type=Path, required=True)
args = parser.parse_args()
fingerprint = hashlib.sha256(args.certificate.read_bytes()).hexdigest().encode()
expected = {'arm64-v8a': 183, 'armeabi-v7a': 40, 'x86_64': 62}
apks = list(args.directory.rglob('*.apk'))
modules = list(args.directory.rglob('*_kernelsu.ko'))
assert apks, 'No APK artifacts'
for apk in apks:
    with zipfile.ZipFile(apk) as archive:
        abis = {name.split('/')[1] for name in archive.namelist()
                if name.startswith('lib/') and name.endswith('/libksud.so')}
        assert abis, f'{apk}: missing daemon'
        for abi in abis:
            for library in ['libksud.so', 'libkernelsu.so', 'libadbroot.so']:
                data = archive.read(f'lib/{abi}/{library}')
                assert data[:4] == b'\x7fELF'
                assert struct.unpack_from('<H', data, 18)[0] == expected[abi], (apk, abi, library)
    print(f'{apk.name}: verified {", ".join(sorted(abis))}')
for module in modules:
    data = module.read_bytes()
    assert data[:4] == b'\x7fELF', module
    assert fingerprint in data, f'{module}: manager certificate not pinned'
    assert b'vermagic=' in data, f'{module}: no kernel vermagic'
print(f'Verified {len(apks)} APKs and {len(modules)} kernel modules.')
