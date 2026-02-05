# TRCC Linux Documentation

## Contents

| File | Description |
|------|-------------|
| [TECHNICAL_REFERENCE.md](TECHNICAL_REFERENCE.md) | Devices, protocol, FBL detection, Windows/Linux architecture |
| [09_Handshake_Protocol_Timing.txt](09_Handshake_Protocol_Timing.txt) | Critical handshake timing rules |

## Quick Links

- [Main README](../README.md) - Installation and usage
- [Settings](../data/settings.json) - Configuration
- [Themes](../data/) - Theme directories (Theme320320, etc.)

## Windows TRCC Reference

The Linux port is based on reverse-engineering the Windows TRCC application. Key namespaces:

| Namespace | Purpose |
|-----------|---------|
| `TRCC` | Main shell (Form1, UCDevice, UCAbout) |
| `TRCC.CZTV` | LCD controller (FormCZTV = Color Screen Display) |
| `TRCC.DCUserControl` | 50+ reusable UI components |
| `TRCC.LED` / `TRCC.KVMALED6` | LED/RGB controllers |
| `TRCC.Properties` | 670 embedded resources |

See [TECHNICAL_REFERENCE.md](TECHNICAL_REFERENCE.md) for full details on UI specs and color values.
