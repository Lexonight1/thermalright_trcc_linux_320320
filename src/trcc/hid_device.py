#!/usr/bin/env python3
"""
HID USB protocol layer for Type 2 ("H") and Type 3 ("ALi") LCD devices.

These devices use USB bulk transfers instead of SCSI.  Protocol details
reverse-engineered from the decompiled USBLCDNEW.exe (C# / LibUsbDotNet).

Type 2 — VID 0x0416, PID 0x530A  ("H" variant)
Type 3 — VID 0x0416, PID 0x53E6  ("ALi" variant)

The ``UsbTransport`` ABC abstracts the raw USB I/O so that:
  • Tests can inject a mock transport (no real hardware needed).
  • A real libusb/pyusb backend can be swapped in later.
"""

import struct
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Set


# =========================================================================
# Constants (from USBLCDNEW.decompiled.cs)
# =========================================================================

# USB IDs
TYPE2_VID = 0x0416
TYPE2_PID = 0x530A

TYPE3_VID = 0x0416
TYPE3_PID = 0x53E6

# Endpoint addresses (LibUsbDotNet enum values)
EP_READ_01 = 0x81   # ReadEndpointID.Ep01
EP_WRITE_01 = 0x01  # WriteEndpointID.Ep01
EP_WRITE_02 = 0x02  # WriteEndpointID.Ep02

# Type 2 magic bytes
TYPE2_MAGIC = bytes([0xDA, 0xDB, 0xDC, 0xDD])

# Type 3 command prefix
TYPE3_CMD_PREFIX = bytes([0xF5, 0x00, 0x01, 0x00, 0xBC, 0xFF, 0xB6, 0xC8])
TYPE3_FRAME_PREFIX = bytes([0xF5, 0x01, 0x01, 0x00, 0xBC, 0xFF, 0xB6, 0xC8])

# Buffer / packet sizes
TYPE2_INIT_SIZE = 512
TYPE2_RESPONSE_SIZE = 512
TYPE3_INIT_SIZE = 1040   # 16-byte header + 1024 zeros
TYPE3_RESPONSE_SIZE = 1024
TYPE3_DATA_SIZE = 204800  # 320*320*2, fixed payload size
TYPE3_FRAME_TOTAL = 204816  # 16-byte prefix + 204800 data
TYPE3_ACK_SIZE = 16

# Alignment
USB_BULK_ALIGNMENT = 512

# Default timeout (ms)
DEFAULT_TIMEOUT_MS = 100


# =========================================================================
# Data classes
# =========================================================================

@dataclass
class DeviceInfo:
    """Information extracted from a device handshake response."""
    device_type: int          # 2 or 3
    mode_byte_1: int = 0     # Type 2: resp[4], Type 3: resp[0]-1
    mode_byte_2: int = 0     # Type 2: resp[5], Type 3: 0
    serial: str = ""         # Hex string from response
    fbl: Optional[int] = None  # Type 3 only: resp[0]-1


# =========================================================================
# Abstract USB transport
# =========================================================================

class UsbTransport(ABC):
    """Abstract USB bulk transport — mockable for testing."""

    @abstractmethod
    def open(self) -> None:
        """Open the USB device and claim interface."""

    @abstractmethod
    def close(self) -> None:
        """Release interface and close."""

    @abstractmethod
    def write(self, endpoint: int, data: bytes, timeout: int = DEFAULT_TIMEOUT_MS) -> int:
        """Bulk write to endpoint.  Returns bytes transferred."""

    @abstractmethod
    def read(self, endpoint: int, length: int, timeout: int = DEFAULT_TIMEOUT_MS) -> bytes:
        """Bulk read from endpoint.  Returns data read."""

    @property
    @abstractmethod
    def is_open(self) -> bool:
        """Whether the device is currently open."""


# =========================================================================
# Helpers
# =========================================================================

def _ceil_to_512(n: int) -> int:
    """Round *n* up to the next multiple of 512 (or *n* itself if aligned).

    Matches the C# expression::

        n / 512 * 512 + ((n % 512 != 0) ? 512 : 0)
    """
    return (n // USB_BULK_ALIGNMENT) * USB_BULK_ALIGNMENT + (
        USB_BULK_ALIGNMENT if n % USB_BULK_ALIGNMENT else 0
    )


# =========================================================================
# Type 2 — "H" variant  (VID 0x0416, PID 0x530A)
# =========================================================================

class HidDeviceType2:
    """Protocol handler for Type 2 HID LCD devices.

    Uses Ep01 for reads, Ep02 for writes.
    Image data is sent with a 20-byte header, 512-byte aligned.
    """

    def __init__(self, transport: UsbTransport):
        self.transport = transport
        self._initialized = False
        self.device_info: Optional[DeviceInfo] = None

    # -- Init packet ---------------------------------------------------

    @staticmethod
    def build_init_packet() -> bytes:
        """Build the 512-byte handshake packet.

        Layout (from C#)::

            [0xDA, 0xDB, 0xDC, 0xDD,   # magic
             0,0,0,0, 0,0,0,0,          # reserved
             0x01, 0,0,0,               # command = 1
             0,0,0,0]                   # reserved
            + 492 zero bytes            # padding to 512
        """
        header = (
            TYPE2_MAGIC
            + b'\x00' * 8
            + b'\x01\x00\x00\x00'
            + b'\x00' * 4
        )
        return header + b'\x00' * (TYPE2_INIT_SIZE - len(header))

    # -- Response parsing -----------------------------------------------

    @staticmethod
    def validate_response(resp: bytes) -> bool:
        """Check the handshake response matches expected pattern.

        Conditions (from C#)::

            resp[0]==0xDA && resp[1]==0xDB && resp[2]==0xDC && resp[3]==0xDD
            && resp[12]==1 && resp[16]==0x10
        """
        if len(resp) < TYPE2_RESPONSE_SIZE:
            return False
        return (
            resp[0:4] == TYPE2_MAGIC
            and resp[12] == 0x01
            and resp[16] == 0x10
        )

    @staticmethod
    def parse_device_info(resp: bytes) -> DeviceInfo:
        """Extract device info from a validated handshake response.

        From C#::

            mode1 = resp[4], mode2 = resp[5]
            serial = hex string of resp[20:36]
        """
        serial = resp[20:36].hex().upper()
        return DeviceInfo(
            device_type=2,
            mode_byte_1=resp[4],
            mode_byte_2=resp[5],
            serial=serial,
        )

    # -- Handshake -------------------------------------------------------

    def handshake(self) -> DeviceInfo:
        """Perform the init handshake.

        Sends init packet on Ep02, reads response on Ep01, validates,
        and returns :class:`DeviceInfo`.

        Raises:
            RuntimeError: If the handshake fails.
        """
        init_pkt = self.build_init_packet()
        self.transport.write(EP_WRITE_02, init_pkt, DEFAULT_TIMEOUT_MS)
        resp = self.transport.read(EP_READ_01, TYPE2_RESPONSE_SIZE, DEFAULT_TIMEOUT_MS)

        if not self.validate_response(resp):
            raise RuntimeError("Type 2 handshake failed: invalid response")

        self.device_info = self.parse_device_info(resp)
        self._initialized = True
        return self.device_info

    # -- Frame send -------------------------------------------------------

    @staticmethod
    def build_frame_packet(image_data: bytes) -> bytes:
        """Build a frame packet from raw image data.

        The 20-byte header is structured so that bytes[16:20] contain
        the image data length as a little-endian uint32.  The rest of
        the header is zeros (populated by the TRCC GUI in Windows via
        shared memory; we only need the size field for the device to
        parse it).

        The total transfer length is rounded up to the next 512-byte
        boundary.

        Returns the padded packet ready for USB bulk write.
        """
        data_len = len(image_data)
        # 20-byte header: 16 zero bytes + LE uint32 image size
        header = b'\x00' * 16 + struct.pack('<I', data_len)
        raw = header + image_data
        padded_len = _ceil_to_512(len(raw))
        return raw.ljust(padded_len, b'\x00')

    def send_frame(self, image_data: bytes) -> bool:
        """Send one image frame to the device.

        Args:
            image_data: Raw image bytes (JPEG or other format the
                        device expects).

        Returns:
            True if the transfer succeeded.

        Raises:
            RuntimeError: If device not initialized.
        """
        if not self._initialized:
            raise RuntimeError("Type 2 device not initialized — call handshake() first")

        packet = self.build_frame_packet(image_data)
        transferred = self.transport.write(EP_WRITE_02, packet, DEFAULT_TIMEOUT_MS)
        return transferred > 0


# =========================================================================
# Type 3 — "ALi" variant  (VID 0x0416, PID 0x53E6)
# =========================================================================

class HidDeviceType3:
    """Protocol handler for Type 3 HID LCD devices.

    Uses Ep01 for reads, Ep02 for writes.
    Fixed-size 204816-byte frame writes with 16-byte ACK read.
    """

    def __init__(self, transport: UsbTransport):
        self.transport = transport
        self._initialized = False
        self.device_info: Optional[DeviceInfo] = None

    # -- Init packet ---------------------------------------------------

    @staticmethod
    def build_init_packet() -> bytes:
        """Build the 1040-byte handshake packet.

        Layout (from C#)::

            [0xF5, 0x00, 0x01, 0x00,
             0xBC, 0xFF, 0xB6, 0xC8,
             0x00, 0x00, 0x00, 0x00,
             0x00, 0x04, 0x00, 0x00]   # 16-byte prefix
            + 1024 zero bytes          # padding
        """
        prefix = (
            TYPE3_CMD_PREFIX
            + b'\x00\x00\x00\x00'
            + b'\x00\x04\x00\x00'
        )
        return prefix + b'\x00' * 1024

    # -- Response parsing -----------------------------------------------

    @staticmethod
    def validate_response(resp: bytes) -> bool:
        """Check the handshake response.

        Condition (from C#)::

            resp[0] == 101 (0x65) || resp[0] == 102 (0x66)
        """
        if len(resp) < 14:
            return False
        return resp[0] in (0x65, 0x66)

    @staticmethod
    def parse_device_info(resp: bytes) -> DeviceInfo:
        """Extract device info from a validated handshake response.

        From C#::

            fbl = resp[0] - 1  (100 or 101)
            serial = hex string of resp[10:14]
        """
        serial = resp[10:14].hex().upper()
        fbl = resp[0] - 1
        return DeviceInfo(
            device_type=3,
            mode_byte_1=fbl,
            serial=serial,
            fbl=fbl,
        )

    # -- Handshake -------------------------------------------------------

    def handshake(self) -> DeviceInfo:
        """Perform the init handshake.

        Sends init packet on Ep02, reads response on Ep01, validates,
        and returns :class:`DeviceInfo`.

        Raises:
            RuntimeError: If the handshake fails.
        """
        init_pkt = self.build_init_packet()
        self.transport.write(EP_WRITE_02, init_pkt, DEFAULT_TIMEOUT_MS)
        resp = self.transport.read(EP_READ_01, TYPE3_RESPONSE_SIZE, DEFAULT_TIMEOUT_MS)

        if not self.validate_response(resp):
            raise RuntimeError("Type 3 handshake failed: invalid response")

        self.device_info = self.parse_device_info(resp)
        self._initialized = True
        return self.device_info

    # -- Frame send -------------------------------------------------------

    @staticmethod
    def build_frame_packet(image_data: bytes) -> bytes:
        """Build a frame packet from raw image data.

        16-byte prefix::

            [0xF5, 0x01, 0x01, 0x00,
             0xBC, 0xFF, 0xB6, 0xC8,
             0x00, 0x00, 0x00, 0x00,
             0x00, 0x20, 0x03, 0x00]   # bytes[12:16] = 204800 LE

        Data is padded/truncated to exactly 204800 bytes.
        Total packet = 204816 bytes.
        """
        prefix = (
            TYPE3_FRAME_PREFIX
            + b'\x00\x00\x00\x00'
            + struct.pack('<I', TYPE3_DATA_SIZE)
        )
        # Pad or truncate image data to fixed size
        if len(image_data) < TYPE3_DATA_SIZE:
            padded = image_data + b'\x00' * (TYPE3_DATA_SIZE - len(image_data))
        else:
            padded = image_data[:TYPE3_DATA_SIZE]
        return prefix + padded

    def send_frame(self, image_data: bytes) -> bool:
        """Send one image frame and read ACK.

        Args:
            image_data: Raw image bytes.

        Returns:
            True if the transfer and ACK succeeded.

        Raises:
            RuntimeError: If device not initialized.
        """
        if not self._initialized:
            raise RuntimeError("Type 3 device not initialized — call handshake() first")

        packet = self.build_frame_packet(image_data)
        transferred = self.transport.write(EP_WRITE_02, packet, DEFAULT_TIMEOUT_MS)
        if transferred == 0:
            return False

        # Read 16-byte ACK (C# does: usbEndpointReader.Read(first, 0, 16, 100, ...))
        ack = self.transport.read(EP_READ_01, TYPE3_ACK_SIZE, DEFAULT_TIMEOUT_MS)
        return len(ack) > 0


# =========================================================================
# Public API  (mirrors scsi_device.send_image_to_device)
# =========================================================================

# Track initialized devices by transport identity
_initialized_transports: Set[int] = set()
_device_handlers: dict = {}


def send_image_to_hid_device(
    transport: UsbTransport,
    image_data: bytes,
    device_type: int,
) -> bool:
    """Send image data to a HID LCD device.

    Performs handshake on first call per transport, then sends frames.

    Args:
        transport: Open USB transport to the device.
        image_data: Raw image bytes (JPEG or device-native format).
        device_type: 2 for "H" variant, 3 for "ALi" variant.

    Returns:
        True if the send succeeded.
    """
    transport_id = id(transport)

    try:
        if transport_id not in _initialized_transports:
            if device_type == 2:
                handler = HidDeviceType2(transport)
            elif device_type == 3:
                handler = HidDeviceType3(transport)
            else:
                raise ValueError(f"Unknown HID device type: {device_type}")

            handler.handshake()
            _device_handlers[transport_id] = handler
            _initialized_transports.add(transport_id)

        handler = _device_handlers[transport_id]
        return handler.send_frame(image_data)

    except Exception as e:
        print(f"[!] HID send failed: {e}")
        _initialized_transports.discard(transport_id)
        _device_handlers.pop(transport_id, None)
        return False
