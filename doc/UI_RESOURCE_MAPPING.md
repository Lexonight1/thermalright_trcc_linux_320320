# UI Resource Mapping

A concise mapping of Windows TRCC UI classes to the resource images they reference.

> This file was auto-generated from the decompiled C# sources and serves as a reference for wiring extracted PNGs to Linux UI components.

## Summary (class → resource keys)

- **TRCC.DCUserControl.UCSystemInfoOptionsOne**
  - Background images: `A自定义`, `Acpu`, `Agpu`, `Adram`, `Ahdd`, `Anet`, `Afan`
  - Buttons: `P关闭按钮2`

- **TRCC.DCUserControl.UCXiTongXianShiSub**
  - Select overlay: `P选中`
  - Background images by mode: `P数据`, `P时间`, `P星期`, `P日期`, `P文本`

- **TRCC.DCUserControl.UCXiTongXianShiTable**
  - Buttons / toggles: `P单位开关`, `P单位开关a`, `P12H`, `P24H`, `PYMD`, `PDMY`, `PMD`, `PDM`
  - Panel background: `P01模块设置`

- **TRCC.DCUserControl.UCThemeLocal**
  - Scroll/thumb: `P滚动条按钮`
  - Background: `P0本地主题`
  - Category buttons: `P主题分类选择`, `P主题分类选择0`
  - Carousel images: `P轮播1`..`P轮播6`, fallback `P轮播选框`
  - Close button: `P关闭按钮2`
  - Carousel control: `P主题轮播a`, `P主题轮播`

- **TRCC.DCUserControl.UCXiTongXianShiColor**
  - Color picker: `P取色`, `P吸管`
  - Text/font button: `P文字字体`
  - Background: `P01参数面板`

- **TRCC.DCUserControl.UCXiTongXianShiAdd**
  - Bitmaps: `P点选框`, `P点选框A`
  - Scroll/mask: `P滚动条按钮`, `P01增加内容遮罩`
  - Buttons: `P增加时间`, `P增加星期`, `P增加日期`, `P增加文本`
  - Background: `P01增加内容`

- **TRCC.DCUserControl.UCXiTongXinXi**
  - Switch/slider: `P滑动开`, `P滑动关`
  - Mode buttons: `PM1`..`PM6`, `PM1a`..`PM6a`
  - Selection: `P选择框M`, `P选择框Ma`
  - Multi-select / carousel: `P多选`, `P轮播a`, `P轮播`
  - Font buttons: `P文字字体`, `P数字字体`
  - Background: `P01系统信息`

- **TRCC.DCUserControl.UCThemeSetting**
  - Sub-component backgrounds: `P01播放器`, `P01背景显示`, `P01布局蒙板`, `P01键盘联动1/2/3`, `P01动画联动`, `P01投屏显示xy`
  - Background: `P0主题设置`

- **TRCC.DCUserControl.UCThemeMask**
  - Scroll/thumb: `P滚动条按钮`
  - Background: `p0云端主题`

- **TRCC.DCUserControl.UCTouPingXianShi**
  - Orientation variants: `P01投屏显示xy`, `P01投屏显示xyd`, `P01投屏显示xye`, etc.
  - Buttons: `P功能选择`, `P功能选择a`, `P显示边框`, `P显示边框A`, `P加`, `P减`

- **TRCC.CZTV.FormScreenImage**
  - Power button: `Alogout默认`, `Alogout选中`
  - Form preview background: `P0预览弹窗800X360`

- **TRCC.KVMALED6.FormKVMALED6**
  - Buttons/icons: `Alogout默认`, `Alogout选中`, `D1头盔1`..`D1头盔5`, `D1灯光聚合(a)`, other `D*` images


## Base classes and child UI elements (containers) 🔧

These are Windows "base"/container classes (forms or UserControls) that set a background and create child UI elements (buttons, sub-controls, panels). Use this to wire Linux `UC*` components to the correct background images and child widgets.

- **FormCZTV / Form (FormCZTV)**
  - Children: `UCInfoModule`, `UCPreview`, `UCThemeLocal`, `UCThemeWeb`, `UCThemeSetting`, `UCOverlayEditor`.
  - Note: FormCZTV is the main per-device container; backgrounds applied to panels are passed to child components (e.g., `panel_local`, `panel_cloud`).

- **UCThemeSetting (settings container)**
  - Children (sub-panels): `UCShiPingBoFangQi` (player controls), `UCBeiJingXianShi` (background settings), `UCMengBanXianShi` (layout/mask), `UCJianPanLianDongA/B/C` (keyboard link panels), `UCDongHuaLianDong` (animations), `UCTouPingXianShi` (screen/display settings), `UCAbout`.
  - Note: `UCThemeSetting` sets each sub-panel's BackgroundImage via resources like `P01播放器`, `P01背景显示`, `P01布局蒙板`, etc.

- **UCXiTongXianShi (overlay manager)**
  - Children: array of `UCXiTongXianShiSub` elements (display elements such as time/date/hardware/text fields).
  - Note: Each sub-element uses its own background (e.g., `P数据`, `P时间`) and a selection overlay (`P选中`).

- **UCThemeLocal (local themes page)**
  - Children: theme grid, carousel controls, category buttons, pagination buttons, thumbnails; uses `P0本地主题`, `P滚动条按钮`, `P主题分类选择`.

- **UCXiTongXinXi (system info panel)**
  - Children: mode buttons `PM1..PM6`, selection box buttons, toggle buttons (on/off), numeric/font controls; backgrounds set from `P01系统信息` and specific control images.

- **UCBeiJingXianShi (background display)**
  - Children: background selection controls and preview area; sets background (e.g., `P01背景显示`).

- **UCShiPingBoFangQi (player control)**
  - Children: play/pause, timeline, preview thumbnails; background `P01播放器`.

- **UCThemeMask / UCMengBanXianShi (mask/layout)**
  - Children: mask overlay controls, track/scroll images; background `p0云端主题` / `P01增加内容遮罩`.

- **KVMALED6 / LED forms**
  - Children: multiple button panels using `D*` resources for icons; backgrounds applied to control groups.

---

## Language equivalents 🌐

Many resource images include language-specific variants. Naming follows the Windows TRCC convention where a language suffix is appended to the base filename. Examples:

- `A0关于.png`            → Simplified Chinese (default, no suffix)
- `A0关于en.png`          → English
- `A0关于d.png`           → German
- `A0关于e.png`           → Spanish
- `A0关于tc.png`          → Traditional Chinese

Supported language suffixes (used in `src/trcc/resources.py`): **en** (English), **tc** (Traditional Chinese), **d** (German), **e** (Spanish), **f** (French), **p** (Portuguese), **r** (Russian), **x** (Japanese), and default (Simplified Chinese, no suffix).

The repository provides a `ResourceLoader` (`src/trcc/resources.py`) that resolves language variants automatically: it first looks for `base+suffix.png` (matching the selected language) and falls back to `base.png` if a localized file does not exist. Use `ResourceLoader.set_language(lang_code)` to switch languages at runtime and let the loader pick the correct PNGs.

**Guidance:** When mapping resources in this document or wiring UI code, prefer using logical resource keys (e.g., `panel.main`, `settings.background`) and rely on the `ResourceLoader` to pick the appropriate language file. If you add or extract a localized PNG, place it in `assets/extracted_resx/` using the same base name + suffix pattern.

Notes:
- The referenced resource keys correspond to extracted PNGs in `assets/extracted_resx/` (e.g., `assets/extracted_resx/TRCC.Properties.Resources/P关闭按钮2.png`).
- This document intentionally lists resource usage (concise). If you want file/line references or coordinates (Location/Size), I can run a deeper parse and add them.

Generated automatically and committed to branch `ui-mapping`.
