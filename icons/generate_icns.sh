#!/bin/bash
# macOS App Icon 生成脚本
# 从 SVG 生成 .icns 文件
#
# 依赖: rsvg-convert (brew install librsvg)
# 用法: ./generate_icns.sh app_icon.svg AppIcon.icns

set -e

SVG_INPUT="${1:-app_icon.svg}"
ICNS_OUTPUT="${2:-AppIcon.icns}"
ICONSET_DIR="/tmp/AppIcon_$$.iconset"

# 检查依赖
if ! command -v rsvg-convert &> /dev/null; then
    echo "错误: 需要安装 rsvg-convert"
    echo "运行: brew install librsvg"
    exit 1
fi

if [ ! -f "$SVG_INPUT" ]; then
    echo "错误: 找不到 SVG 文件: $SVG_INPUT"
    exit 1
fi

echo "从 $SVG_INPUT 生成 $ICNS_OUTPUT ..."

# 创建 iconset 目录
mkdir -p "$ICONSET_DIR"

# 生成各种尺寸
for size in 16 32 128 256 512; do
    rsvg-convert -w $size -h $size "$SVG_INPUT" -o "$ICONSET_DIR/icon_${size}x${size}.png"
    echo "  生成 ${size}x${size}"
done

# 生成 @2x 版本
rsvg-convert -w 1024 -h 1024 "$SVG_INPUT" -o "$ICONSET_DIR/icon_512x512@2x.png"
cp "$ICONSET_DIR/icon_32x32.png" "$ICONSET_DIR/icon_16x16@2x.png"
rsvg-convert -w 64 -h 64 "$SVG_INPUT" -o "$ICONSET_DIR/icon_32x32@2x.png"
cp "$ICONSET_DIR/icon_256x256.png" "$ICONSET_DIR/icon_128x128@2x.png"
cp "$ICONSET_DIR/icon_512x512.png" "$ICONSET_DIR/icon_256x256@2x.png"

# 生成 icns
iconutil -c icns "$ICONSET_DIR" -o "$ICNS_OUTPUT"

# 清理
rm -rf "$ICONSET_DIR"

echo "完成: $ICNS_OUTPUT"
