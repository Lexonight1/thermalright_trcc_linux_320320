"""Shared constants for TRCC Linux.

Format modes matching Windows TRCC (UCXiTongXianShiSub.cs).
FBL/PM resolution mapping from FormCZTV.cs.
"""

# Time formats:
#   case 0: DateTime.Now.ToString("HH:mm")
#   case 1: DateTime.Now.ToString("hh:mm tt", CultureInfo.InvariantCulture)
#   case 2: DateTime.Now.ToString("HH:mm")  -- same as case 0
TIME_FORMATS = {
    0: "%H:%M",       # 24-hour (14:58)
    1: "%-I:%M %p",   # 12-hour with AM/PM, no leading zero (2:58 PM)
    2: "%H:%M",       # 24-hour (same as mode 0 in Windows)
}

# Date formats:
#   case 0, 1: DateTime.Now.ToString("yyyy/MM/dd")
#   case 2: DateTime.Now.ToString("dd/MM/yyyy")
#   case 3: DateTime.Now.ToString("MM/dd")
#   case 4: DateTime.Now.ToString("dd/MM")
DATE_FORMATS = {
    0: "%Y/%m/%d",    # 2026/01/30
    1: "%Y/%m/%d",    # 2026/01/30 (same as mode 0 in Windows)
    2: "%d/%m/%Y",    # 30/01/2026
    3: "%m/%d",       # 01/30
    4: "%d/%m",       # 30/01
}

# Weekday names matching Windows TRCC (English)
# Windows DayOfWeek: Sunday=0, Saturday=6
# Python weekday(): Monday=0, Sunday=6
# Array adapted for Python's weekday() numbering
WEEKDAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]

# Chinese weekday names (for Language == 1)
WEEKDAYS_CN = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]

# =========================================================================
# FBL → Resolution mapping (from FormCZTV.cs lines 811-821)
# =========================================================================
# FBL (Frame Buffer Layout) byte determines LCD resolution.
# For SCSI devices, the poll byte IS the FBL (PM=FBL).
# For HID Type 3, FBL = resp[0]-1.
# For HID Type 2, FBL is derived from PM via pm_to_fbl() in device_hid.py.
FBL_TO_RESOLUTION: dict[int, tuple[int, int]] = {
    36:  (240, 240),
    37:  (240, 240),
    50:  (240, 320),
    51:  (320, 240),
    54:  (360, 360),
    64:  (640, 480),
    72:  (480, 480),
    100: (320, 320),
    101: (320, 320),
    102: (320, 320),
    114: (1600, 720),
    128: (1280, 480),
    192: (1920, 462),
    # FBL 224 is overloaded — depends on PM, defaults to 854x480
    224: (854, 480),
}

# Reverse lookup: resolution → PM/FBL (first match wins).
# Used by SCSI to resolve button images from detected resolution.
RESOLUTION_TO_PM: dict[tuple[int, int], int] = {
    res: fbl for fbl, res in FBL_TO_RESOLUTION.items()
    if fbl not in (37, 101, 102, 224)  # skip duplicates/overloaded
}
