#!/bin/bash
# Build the universal app and wrap it in an installer package.
set -euo pipefail
cd "$(dirname "$0")"

rm -rf build dist
VERSION=$(.venv/bin/python -c "import sys; sys.path.insert(0, 'src'); import version; print(version.VERSION)")
echo "Building version $VERSION"
.venv/bin/python setup.py py2app > build.log 2>&1 || { tail -30 build.log; exit 1; }

APP="dist/Dynamic Island.app"
echo "Architectures of the app's binaries:"
lipo -archs "$APP/Contents/MacOS/Dynamic Island"
# Every compiled file inside the bundle must carry both architectures.
BAD=$(find "$APP" -type f \( -name "*.so" -o -name "*.dylib" \) -exec sh -c 'lipo -archs "$1" 2>/dev/null | grep -q "x86_64.*arm64\|arm64.*x86_64" || echo "$1"' _ {} \;)
if [ -n "$BAD" ]; then echo "Not universal:"; echo "$BAD"; exit 1; fi

# py2app records the build machine's Python path as metadata; a standalone app never reads it,
# so replace it rather than ship a personal folder name.
/usr/libexec/PlistBuddy -c "Set :PythonInfoDict:PythonExecutable python" "$APP/Contents/Info.plist"
if grep -rq "$HOME" "$APP/Contents/Info.plist" "$APP/Contents/Resources/"*.py 2>/dev/null; then
  echo "Build still contains a personal path:"; grep -rl "$HOME" "$APP/Contents/Info.plist" "$APP/Contents/Resources/"*.py; exit 1
fi

codesign --force --deep --sign - "$APP"          # ad-hoc signature (no Developer ID)

# Stage the app and pin it to /Applications: without this the installer may "relocate" the
# install onto any other copy of the app it finds on the disk (such as the one in dist/).
rm -rf build/pkgroot && mkdir -p build/pkgroot
cp -R "$APP" build/pkgroot/
pkgbuild --analyze --root build/pkgroot build/component.plist > /dev/null
/usr/libexec/PlistBuddy -c "Add :0:BundleIsRelocatable bool false" build/component.plist 2>/dev/null \
  || /usr/libexec/PlistBuddy -c "Set :0:BundleIsRelocatable false" build/component.plist
/usr/libexec/PlistBuddy -c "Set :0:BundleIsVersionChecked false" build/component.plist

# The scripts quit a running copy before installing and start the new one afterwards.
pkgbuild --root build/pkgroot --component-plist build/component.plist --install-location /Applications \
         --scripts packaging/scripts --identifier com.dynamicisland.app --version "$VERSION" \
         "dist/Dynamic Island.pkg"
echo "Built: dist/Dynamic Island.pkg"
