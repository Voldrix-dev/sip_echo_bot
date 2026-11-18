#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# baresip-python native build
#
# Supported:
#   - Manjaro / Arch
#   - Ubuntu / Debian
#
# Architecture:
#
#   1. System packages
#        pacman / apt
#
#   2. uv Python
#        Used for building embedded baresip
#
#   3. TARGET VENV
#        $VENV/bin/python
#
#        Used for:
#          - cffi
#          - numpy
#          - PySide6
#          - QtAwesome
#          - evdev
#          - build_ffi.py
#          - installing baresip-python
#          - import tests
#
# IMPORTANT:
#   _native.so is built by TARGET Python.
#
# The TARGET venv is created automatically.
#
# The script also creates:
#
#   ~/.local/share/applications/Video Echo Bot.desktop
#
# and, if ~/Desktop exists:
#
#   ~/Desktop/Video Echo Bot.desktop
#
# ============================================================


# ------------------------------------------------------------
# Configuration
# ------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

REPO="${REPO:-$SCRIPT_DIR/baresip-python}"
VENV="${VENV:-$HOME/.venv}"

PYTHON="${VENV}/bin/python"

# Python used by uv for building embedded baresip
UV_PYTHON="${UV_PYTHON:-3.12}"


# ------------------------------------------------------------
# Application launched by the desktop shortcut
# ------------------------------------------------------------

APP_SCRIPT="${APP_SCRIPT:-$SCRIPT_DIR/video_bot/main.py}"

APP_NAME="Video Echo Bot"
APP_COMMENT="SIP bot with video echo"

DESKTOP_FILE_NAME="Video Echo Bot.desktop"


# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------

info() {
    echo
    echo "==> $*"
}

die() {
    echo
    echo "ERROR: $*" >&2
    exit 1
}

need_cmd() {
    command -v "$1" >/dev/null 2>&1 || \
        die "Command not found: $1"
}

pkg_ok() {
    pkg-config --exists "$1" 2>/dev/null
}


# ------------------------------------------------------------
# Detect distribution
# ------------------------------------------------------------

[[ -f /etc/os-release ]] || \
    die "/etc/os-release not found"

source /etc/os-release

case "${ID:-}" in
    manjaro)
        DISTRO="manjaro"
        ;;
    arch)
        DISTRO="arch"
        ;;
    ubuntu)
        DISTRO="ubuntu"
        ;;
    debian)
        DISTRO="debian"
        ;;
    *)
        if [[ "${ID_LIKE:-}" == *debian* ]]; then
            DISTRO="ubuntu"
        elif [[ "${ID_LIKE:-}" == *arch* ]]; then
            DISTRO="manjaro"
        else
            die "Unsupported distribution: ID=${ID:-unknown}, ID_LIKE=${ID_LIKE:-unknown}"
        fi
        ;;
esac

info "Detected distribution: ${PRETTY_NAME:-$ID}"


# ------------------------------------------------------------
# Install system dependencies
# ------------------------------------------------------------

install_deps_manjaro() {

    info "Checking Manjaro/Arch dependencies"

    local missing=""

    for pkg in git base-devel cmake pkgconf openssl opus libvpx v4l-utils ffmpeg x264 uv; do
        if ! pacman -Q "$pkg" >/dev/null 2>&1; then
            missing="$missing $pkg"
        fi
    done

    if [ -n "$missing" ]; then
        info "Installing missing packages:$missing"
        sudo pacman -S --noconfirm --needed $missing
    else
        info "All required packages already installed"
    fi
}


install_deps_ubuntu() {

    info "Installing Ubuntu/Debian dependencies"

    sudo apt-get update

    sudo apt-get install -y \
        git \
        build-essential \
        cmake \
        pkg-config \
        libssl-dev \
        libopus-dev \
        libvpx-dev \
        libasound2-dev \
        libavcodec-dev \
        libavutil-dev \
        libswresample-dev \
        libavformat-dev \
        libx264-dev \
        ffmpeg \
        v4l-utils \
        python3 \
        python3-venv \
        python3-dev \
        python3-pip \
        curl
}


case "$DISTRO" in
    manjaro|arch)
        install_deps_manjaro
        ;;
    ubuntu|debian)
        install_deps_ubuntu
        ;;
esac


# ------------------------------------------------------------
# Check required commands
# ------------------------------------------------------------

need_cmd git
need_cmd cmake
need_cmd pkg-config


# ------------------------------------------------------------
# Install / detect uv
# ------------------------------------------------------------

if ! command -v uv >/dev/null 2>&1; then

    info "uv not found, installing it"

    if [[ "$DISTRO" == "manjaro" || "$DISTRO" == "arch" ]]; then

        sudo pacman -S --needed uv

    else

        curl -LsSf https://astral.sh/uv/install.sh | sh

        export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
    fi
fi

need_cmd uv

info "uv version"
uv --version


# ------------------------------------------------------------
# Install requested Python using uv
# ------------------------------------------------------------

info "Installing Python ${UV_PYTHON} with uv"

uv python install "$UV_PYTHON"


# ------------------------------------------------------------
# Prepare TARGET Python venv
# ------------------------------------------------------------

info "Preparing TARGET Python environment"

mkdir -p "$(dirname "$VENV")"


if [[ -x "$PYTHON" ]]; then

    info "Target venv already exists"

else

    info "Creating target venv"

    echo "  $VENV"

    uv venv \
        --python "$UV_PYTHON" \
        "$VENV"
fi


[[ -x "$PYTHON" ]] || \
    die "Failed to create target Python venv: $VENV"


# ------------------------------------------------------------
# Target Python information
# ------------------------------------------------------------

info "Target Python"

"$PYTHON" --version

echo
echo "Executable:"
"$PYTHON" -c \
    'import sys; print(sys.executable)'

echo
echo "Python prefix:"
"$PYTHON" -c \
    'import sys; print(sys.prefix)'

echo
echo "SOABI:"
"$PYTHON" -c \
    'import sysconfig; print(sysconfig.get_config_var("SOABI"))'


# ------------------------------------------------------------
# Verify pip
# ------------------------------------------------------------

if ! "$PYTHON" -m pip --version >/dev/null 2>&1; then

    info "pip not found in target venv"

    "$PYTHON" -m ensurepip --upgrade || true
fi


if ! "$PYTHON" -m pip --version >/dev/null 2>&1; then

    die "pip is not available in target venv: $VENV"
fi


# ------------------------------------------------------------
# Prepare TARGET Python environment
# ------------------------------------------------------------

info "Upgrading target Python build tools"

"$PYTHON" -m pip install --upgrade \
    pip \
    setuptools \
    wheel


# ------------------------------------------------------------
# Install Python dependencies
# ------------------------------------------------------------

info "Installing target Python dependencies"

"$PYTHON" -m pip install \
    cffi \
    numpy \
    packaging \
    typing-extensions \
    PySide6 \
    QtAwesome \
    evdev


# ------------------------------------------------------------
# Verify TARGET Python environment
# ------------------------------------------------------------

info "Verifying target Python environment"

"$PYTHON" - <<'PY'
import sys
import sysconfig

print("Python:")
print(" ", sys.version)

print("Executable:")
print(" ", sys.executable)

print("Prefix:")
print(" ", sys.prefix)

print("SOABI:")
print(" ", sysconfig.get_config_var("SOABI"))

print()

import cffi
import numpy
import packaging
import typing_extensions
import PySide6
import qtawesome
import evdev

print("cffi:")
print(" ", cffi.__version__)

print("numpy:")
print(" ", numpy.__version__)

print("packaging:")
print(" ", packaging.__version__)

print("typing-extensions: OK")

print("PySide6:")
print(" ", PySide6.__version__)

print("QtAwesome:")
print(" ", qtawesome.__version__)

print("evdev:")
print(" ", getattr(evdev, "__version__", "installed"))

print()
print("Target Python environment: OK")
PY


# ------------------------------------------------------------
# FFmpeg diagnostics
# ------------------------------------------------------------

if command -v ffmpeg >/dev/null 2>&1; then

    info "FFmpeg"

    ffmpeg -version | head -n 1

else

    die "ffmpeg not found"
fi


# ------------------------------------------------------------
# Check FFmpeg runtime
# ------------------------------------------------------------

info "Checking FFmpeg runtime"

if ! ffmpeg -version >/dev/null 2>&1; then

    echo
    echo "FFmpeg exists but cannot start."
    echo
    echo "Missing libraries:"

    ldd "$(command -v ffmpeg)" |
        grep "not found" ||
        true

    echo

    die "FFmpeg runtime check failed"
fi


# ------------------------------------------------------------
# FFmpeg pkg-config
# ------------------------------------------------------------

info "FFmpeg pkg-config"

echo "libavcodec:"
pkg-config --modversion libavcodec 2>/dev/null || true

echo "libavutil:"
pkg-config --modversion libavutil 2>/dev/null || true

echo "libswresample:"
pkg-config --modversion libswresample 2>/dev/null || true

echo "libavformat:"
pkg-config --modversion libavformat 2>/dev/null || true


# ------------------------------------------------------------
# Check x264
# ------------------------------------------------------------

info "Checking x264"

if pkg-config --exists x264; then

    echo "x264:"
    pkg-config --modversion x264

else

    echo "WARNING: pkg-config cannot find x264"
fi


# ------------------------------------------------------------
# Clone / update repository
# ------------------------------------------------------------

if [[ ! -d "$REPO/.git" ]]; then

    info "Cloning baresip-python"

    git clone --recurse-submodules \
        https://github.com/daily-co/baresip-python.git \
        "$REPO"

else

    info "Updating existing baresip-python repository"

    cd "$REPO"

    git fetch --all --tags

    git submodule sync --recursive
    git submodule update --init --recursive
fi

cd "$REPO"


# ------------------------------------------------------------
# Make sure submodules are present
# ------------------------------------------------------------

info "Updating git submodules"

git submodule sync --recursive
git submodule update --init --recursive


# ------------------------------------------------------------
# Prepare uv project environment
# ------------------------------------------------------------

info "Preparing uv project environment"

uv python install "$UV_PYTHON"

uv sync --group dev


# ------------------------------------------------------------
# Build embedded baresip
# ------------------------------------------------------------

info "Building baresip with FFmpeg avcodec"

export BARESIP_EXTRA_MODULES=avcodec

uv run python scripts/build_native.py


# ------------------------------------------------------------
# Verify native baresip build
# ------------------------------------------------------------

BARESIP_STATIC_LIB="$REPO/third_party/baresip/build/libbaresip.a"

[[ -f "$BARESIP_STATIC_LIB" ]] || \
    die "libbaresip.a not found: $BARESIP_STATIC_LIB"


info "Embedded baresip build successful"

echo "  $BARESIP_STATIC_LIB"


# ------------------------------------------------------------
# Verify avcodec module
# ------------------------------------------------------------

info "Checking avcodec module"

AVCODEC_FILES="$(
    find \
        "$REPO/third_party/baresip/build" \
        -type f \
        \( \
            -name '*avcodec*' \
            -o \
            -name 'avcodec.o' \
        \) \
        -print 2>/dev/null ||
        true
)"

if [[ -z "$AVCODEC_FILES" ]]; then

    echo "WARNING: avcodec object/library was not found"

else

    echo "$AVCODEC_FILES"
fi


# ------------------------------------------------------------
# Modify Python shim
# ------------------------------------------------------------

SHIM="$REPO/src/_native/shim.c"

[[ -f "$SHIM" ]] || \
    die "shim.c not found: $SHIM"


info "Checking bp_modules[] for avcodec"


if grep -Eq '"avcodec"' "$SHIM"; then

    echo "avcodec already present in shim.c"

else

    info "Adding avcodec to bp_modules[]"

    "$PYTHON" - "$SHIM" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])

text = path.read_text()

needle = '    "g711", "libg722", "opus", "vp8", "srtp",'

if needle in text:

    replacement = (
        '    "g711", "libg722", "opus", '
        '"vp8", "avcodec", "srtp",'
    )

    text = text.replace(
        needle,
        replacement,
        1
    )

else:

    start = text.find("bp_modules[]")

    if start == -1:
        raise SystemExit(
            "Cannot find bp_modules[] in shim.c"
        )

    pos = text.find('"vp8"', start)

    if pos == -1:
        raise SystemExit(
            "Cannot find vp8 entry in bp_modules[]"
        )

    pos += len('"vp8"')

    text = (
        text[:pos]
        + ', "avcodec"'
        + text[pos:]
    )

path.write_text(text)
PY

fi


# ------------------------------------------------------------
# Display module list
# ------------------------------------------------------------

info "Current bp_modules[] entries"

sed -n \
    '/bp_modules\[\]/,/};/p' \
    "$SHIM" |
    head -n 40


grep -q '"avcodec"' "$SHIM" || \
    die "avcodec was not added to bp_modules[]"


# ------------------------------------------------------------
# Clean previous Python native extension
# ------------------------------------------------------------

info "Removing previous _native.so"

find "$REPO/src/baresip" \
    -maxdepth 1 \
    -type f \
    -name '_native*.so' \
    -delete


# ------------------------------------------------------------
# Build _native.so using TARGET Python
# ------------------------------------------------------------

info "Building _native.so for TARGET Python"

echo
echo "Python used for _native build:"
"$PYTHON" --version

echo
echo "Executable:"
"$PYTHON" -c \
    'import sys; print(sys.executable)'

echo
echo "CFFI:"
"$PYTHON" -c \
    'import cffi; print(cffi.__version__)'

echo
echo "SOABI:"
"$PYTHON" -c \
    'import sysconfig; print(sysconfig.get_config_var("SOABI"))'


(
    cd "$REPO/src/_native"

    export BP_EXTRA_LIBS="-lavcodec -lavutil -lswresample"

    "$PYTHON" build_ffi.py
)


# ------------------------------------------------------------
# Find generated native extension
# ------------------------------------------------------------

NATIVE_SO="$(
    find "$REPO/src/baresip" \
        -maxdepth 1 \
        -type f \
        -name '_native*.so' \
        -print \
        -quit
)"


[[ -n "$NATIVE_SO" ]] || \
    die "_native.so was not generated"


info "Generated native extension"

echo "  $NATIVE_SO"


# ------------------------------------------------------------
# Check Python ABI
# ------------------------------------------------------------

info "Checking Python ABI"

TARGET_SOABI="$(
    "$PYTHON" -c \
        'import sysconfig; print(sysconfig.get_config_var("SOABI") or "")'
)"

echo "Target SOABI:"
echo "  $TARGET_SOABI"

echo
echo "Native extension:"
echo "  $(basename "$NATIVE_SO")"


if [[ -n "$TARGET_SOABI" ]] &&
   [[ "$(basename "$NATIVE_SO")" == *"$TARGET_SOABI"* ]]; then

    echo "Python ABI: OK"

else

    echo
    echo "WARNING:"
    echo "Native extension name does not explicitly contain target SOABI."
    echo "This is not necessarily an error."
fi


# ------------------------------------------------------------
# Verify FFmpeg linkage
# ------------------------------------------------------------

info "Checking native extension FFmpeg linkage"

FFMPEG_LINKS="$(
    ldd "$NATIVE_SO" 2>/dev/null |
        grep -E \
            'libavcodec|libavutil|libswresample' ||
        true
)"

if [[ -z "$FFMPEG_LINKS" ]]; then

    echo
    echo "WARNING: FFmpeg libraries are not visible through ldd."
    echo
    echo "Full dynamic dependencies:"
    ldd "$NATIVE_SO" || true

else

    echo "$FFMPEG_LINKS"
fi


# ------------------------------------------------------------
# Check unresolved FFmpeg symbols
# ------------------------------------------------------------

info "Checking unresolved FFmpeg symbols"

UNDEFINED_FFMPEG="$(
    nm -D "$NATIVE_SO" 2>/dev/null |
        grep -E \
            ' U av(codec|util|_)' ||
        true
)"

if [[ -n "$UNDEFINED_FFMPEG" ]]; then

    echo "$UNDEFINED_FFMPEG"

else

    echo "No unresolved FFmpeg symbols reported."
fi


# ------------------------------------------------------------
# Install baresip-python into TARGET venv
# ------------------------------------------------------------

info "Installing baresip-python into target venv"

"$PYTHON" -m pip install -e "$REPO"


# ------------------------------------------------------------
# Verify baresip installation
# ------------------------------------------------------------

info "Checking installed baresip package"

"$PYTHON" - <<'PY'
import sys
import sysconfig

print("Python:")
print(" ", sys.version)

print("Executable:")
print(" ", sys.executable)

print("SOABI:")
print(" ", sysconfig.get_config_var("SOABI"))

import baresip

print()
print("baresip import: OK")
print("baresip module:")
print(" ", baresip.__file__)

import baresip._native

print()
print("_native import: OK")
print("_native module:")
print(" ", baresip._native.__file__)
PY


# ------------------------------------------------------------
# Verify native extension through Python
# ------------------------------------------------------------

info "Testing native extension with TARGET Python"

"$PYTHON" - <<'PY'
import baresip._native

print("Native extension loaded successfully.")
PY


# ------------------------------------------------------------
# Verify application script
# ------------------------------------------------------------

info "Checking application entry point"

if [[ ! -f "$APP_SCRIPT" ]]; then

    echo
    echo "Application script was not found:"
    echo "  $APP_SCRIPT"
    echo
    echo "Expected default:"
    echo "  $SCRIPT_DIR/video_bot/main.py"
    echo
    echo "Set APP_SCRIPT to the correct Python file, for example:"
    echo
    echo "  APP_SCRIPT=/path/to/main.py ./build_baresip_python.sh"
    echo

    die "Application entry point does not exist"

fi


info "Application entry point"

echo "  $APP_SCRIPT"


# ------------------------------------------------------------
# Create application launcher
# ------------------------------------------------------------

info "Creating application launcher"

APPLICATIONS_DIR="$HOME/.local/share/applications"

mkdir -p "$APPLICATIONS_DIR"

APPLICATION_DESKTOP_FILE="$APPLICATIONS_DIR/$DESKTOP_FILE_NAME"


cat > "$APPLICATION_DESKTOP_FILE" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=$APP_NAME
Comment=$APP_COMMENT
Exec="$PYTHON" "$APP_SCRIPT"
TryExec="$PYTHON"
Path=$SCRIPT_DIR
Terminal=false
Categories=Utility;
StartupNotify=true
EOF


# Desktop Entry files need executable permission
# for desktop environments that use it for trust handling.

chmod +x "$APPLICATION_DESKTOP_FILE"


info "Application launcher created"

echo "  $APPLICATION_DESKTOP_FILE"


# ------------------------------------------------------------
# Create Desktop shortcut
# ------------------------------------------------------------

DESKTOP_DIR="$HOME/Desktop"

if [[ -d "$DESKTOP_DIR" ]]; then

    info "Creating Desktop shortcut"

    DESKTOP_SHORTCUT="$DESKTOP_DIR/$DESKTOP_FILE_NAME"

    cp "$APPLICATION_DESKTOP_FILE" "$DESKTOP_SHORTCUT"

    chmod +x "$DESKTOP_SHORTCUT"


    # GNOME and some other desktop environments use
    # metadata::trusted for executable desktop files.

    if command -v gio >/dev/null 2>&1; then

        gio set "$DESKTOP_SHORTCUT" \
            metadata::trusted true \
            2>/dev/null ||
            true

    fi


    info "Desktop shortcut created"

    echo "  $DESKTOP_SHORTCUT"

else

    echo
    echo "Desktop directory does not exist:"
    echo "  $DESKTOP_DIR"
    echo
    echo "Application launcher was still installed into:"
    echo "  $APPLICATION_DESKTOP_FILE"
fi


# ------------------------------------------------------------
# Final diagnostics
# ------------------------------------------------------------

info "Final native library dependencies"

ldd "$NATIVE_SO" |
    grep -E \
        'libavcodec|libavutil|libswresample' ||
    true


info "Final native extension symbols"

nm -D "$NATIVE_SO" 2>/dev/null |
    grep -E \
        'avcodec|avutil|swresample|exports_avcodec' |
    head -n 50 ||
    true


# ------------------------------------------------------------
# Final summary
# ------------------------------------------------------------

echo
echo "============================================================"
echo " BUILD SUCCESSFUL"
echo "============================================================"
echo

echo "Repository:"
echo "  $REPO"

echo

echo "Target Python:"
echo "  $PYTHON"

echo

echo "Target Python version:"
"$PYTHON" --version

echo

echo "Native extension:"
echo "  $NATIVE_SO"

echo

echo "Embedded baresip:"
echo "  $BARESIP_STATIC_LIB"

echo

echo "Python modules:"
echo "  cffi"
echo "  numpy"
echo "  packaging"
echo "  typing-extensions"
echo "  PySide6"
echo "  QtAwesome"
echo "  evdev"

echo

echo "Baresip modules:"
echo "  g711"
echo "  libg722"
echo "  opus"
echo "  vp8"
echo "  avcodec"
echo "  srtp"
echo "  dtls_srtp"
echo "  ice"
echo "  stun"
echo "  turn"
echo "  aufile"
echo "  ausine"
echo "  auconv"
echo "  auresamp"
echo "  rtcpsummary"
echo "  alsa"
echo "  v4l2"

echo

echo "Expected video codecs:"
echo "  VP8"
echo "  H.264"
echo "  H.265"

echo

echo "H.264/H.265 backend:"
echo "  FFmpeg avcodec"

echo

echo "Application:"
echo "  $APP_SCRIPT"

echo

echo "Application launcher:"
echo "  $APPLICATION_DESKTOP_FILE"

if [[ -d "$DESKTOP_DIR" ]]; then
    echo
    echo "Desktop shortcut:"
    echo "  $DESKTOP_DIR/$DESKTOP_FILE_NAME"
fi

echo
echo "============================================================"
