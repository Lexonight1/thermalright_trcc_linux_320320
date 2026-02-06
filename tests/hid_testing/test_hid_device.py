"""Mock tests for HID USB protocol (Type 2 and Type 3 devices).

No real USB hardware required — all USB I/O is mocked via UsbTransport.
"""

import struct
from unittest.mock import MagicMock, call, patch

import pytest

from trcc.hid_device import (
    DEFAULT_TIMEOUT_MS,
    EP_READ_01,
    EP_WRITE_02,
    TYPE2_INIT_SIZE,
    TYPE2_MAGIC,
    TYPE2_PID,
    TYPE2_RESPONSE_SIZE,
    TYPE2_VID,
    TYPE3_ACK_SIZE,
    TYPE3_CMD_PREFIX,
    TYPE3_DATA_SIZE,
    TYPE3_FRAME_PREFIX,
    TYPE3_FRAME_TOTAL,
    TYPE3_INIT_SIZE,
    TYPE3_PID,
    TYPE3_RESPONSE_SIZE,
    TYPE3_VID,
    USB_BULK_ALIGNMENT,
    DeviceInfo,
    HidDeviceType2,
    HidDeviceType3,
    UsbTransport,
    _ceil_to_512,
    send_image_to_hid_device,
)


# =========================================================================
# Helpers
# =========================================================================

def _make_mock_transport() -> MagicMock:
    """Create a MagicMock that satisfies the UsbTransport interface."""
    t = MagicMock(spec=UsbTransport)
    t.is_open = True
    return t


def _make_type2_valid_response() -> bytes:
    """Build a valid Type 2 handshake response (512 bytes)."""
    resp = bytearray(TYPE2_RESPONSE_SIZE)
    resp[0:4] = TYPE2_MAGIC           # magic
    resp[4] = 0x02                    # mode byte 1
    resp[5] = 0x03                    # mode byte 2
    resp[12] = 0x01                   # must be 1
    resp[16] = 0x10                   # must be 0x10
    resp[20:36] = b'\xAB\xCD\xEF\x01\x23\x45\x67\x89' * 2  # serial
    return bytes(resp)


def _make_type3_valid_response(first_byte: int = 0x65) -> bytes:
    """Build a valid Type 3 handshake response (1024 bytes)."""
    resp = bytearray(TYPE3_RESPONSE_SIZE)
    resp[0] = first_byte              # 0x65 or 0x66
    resp[10:14] = b'\xDE\xAD\xBE\xEF'  # serial
    return bytes(resp)


# =========================================================================
# _ceil_to_512
# =========================================================================

class TestCeilTo512:
    """Test the 512-byte alignment helper."""

    def test_zero(self):
        assert _ceil_to_512(0) == 0

    def test_exact_multiple(self):
        assert _ceil_to_512(512) == 512
        assert _ceil_to_512(1024) == 1024

    def test_one_byte_over(self):
        assert _ceil_to_512(513) == 1024

    def test_one_byte_under(self):
        assert _ceil_to_512(511) == 512

    def test_small_value(self):
        assert _ceil_to_512(1) == 512
        assert _ceil_to_512(100) == 512

    def test_large_value(self):
        assert _ceil_to_512(10000) == 10240  # 20 * 512

    def test_matches_csharp_formula(self):
        """Verify our impl matches the C# formula for a range of values."""
        for n in range(0, 2049):
            expected = (n // 512) * 512 + (512 if n % 512 != 0 else 0)
            assert _ceil_to_512(n) == expected, f"Failed for n={n}"


# =========================================================================
# Type 2 — Init Packet
# =========================================================================

class TestType2InitPacket:
    """Test HidDeviceType2.build_init_packet() exact bytes."""

    def test_packet_length(self):
        pkt = HidDeviceType2.build_init_packet()
        assert len(pkt) == TYPE2_INIT_SIZE  # 512

    def test_magic_bytes(self):
        pkt = HidDeviceType2.build_init_packet()
        assert pkt[0:4] == bytes([0xDA, 0xDB, 0xDC, 0xDD])

    def test_command_byte(self):
        pkt = HidDeviceType2.build_init_packet()
        assert pkt[12] == 0x01  # command = 1

    def test_reserved_zeros(self):
        pkt = HidDeviceType2.build_init_packet()
        # bytes 4-11 = zeros
        assert pkt[4:12] == b'\x00' * 8
        # bytes 13-19 = zeros
        assert pkt[13:20] == b'\x00' * 7
        # rest = zeros
        assert pkt[20:] == b'\x00' * 492

    def test_byte_by_byte_match(self):
        """Verify the first 20 bytes match the C# array literal exactly."""
        pkt = HidDeviceType2.build_init_packet()
        expected = bytes([
            0xDA, 0xDB, 0xDC, 0xDD,  # magic
            0, 0, 0, 0,              # zeros
            0, 0, 0, 0,              # zeros
            1, 0, 0, 0,              # command = 1
            0, 0, 0, 0,              # zeros
        ])
        assert pkt[:20] == expected


# =========================================================================
# Type 2 — Response Validation
# =========================================================================

class TestType2ResponseValidation:
    """Test HidDeviceType2.validate_response()."""

    def test_valid_response(self):
        resp = _make_type2_valid_response()
        assert HidDeviceType2.validate_response(resp) is True

    def test_wrong_magic_byte_0(self):
        resp = bytearray(_make_type2_valid_response())
        resp[0] = 0xFF
        assert HidDeviceType2.validate_response(bytes(resp)) is False

    def test_wrong_magic_byte_3(self):
        resp = bytearray(_make_type2_valid_response())
        resp[3] = 0x00
        assert HidDeviceType2.validate_response(bytes(resp)) is False

    def test_wrong_command_byte(self):
        resp = bytearray(_make_type2_valid_response())
        resp[12] = 0x00  # must be 1
        assert HidDeviceType2.validate_response(bytes(resp)) is False

    def test_wrong_type_byte(self):
        resp = bytearray(_make_type2_valid_response())
        resp[16] = 0x00  # must be 0x10
        assert HidDeviceType2.validate_response(bytes(resp)) is False

    def test_short_response(self):
        assert HidDeviceType2.validate_response(b'\xDA\xDB\xDC\xDD') is False

    def test_empty_response(self):
        assert HidDeviceType2.validate_response(b'') is False


# =========================================================================
# Type 2 — Device Info Parsing
# =========================================================================

class TestType2DeviceInfo:
    """Test HidDeviceType2.parse_device_info()."""

    def test_basic_extraction(self):
        resp = _make_type2_valid_response()
        info = HidDeviceType2.parse_device_info(resp)
        assert info.device_type == 2
        assert info.mode_byte_1 == 0x02
        assert info.mode_byte_2 == 0x03

    def test_serial_extraction(self):
        resp = bytearray(TYPE2_RESPONSE_SIZE)
        resp[0:4] = TYPE2_MAGIC
        resp[20:36] = bytes(range(16))  # 0x00..0x0F
        info = HidDeviceType2.parse_device_info(bytes(resp))
        assert info.serial == "000102030405060708090A0B0C0D0E0F"

    def test_fbl_is_none(self):
        """Type 2 doesn't have FBL."""
        resp = _make_type2_valid_response()
        info = HidDeviceType2.parse_device_info(resp)
        assert info.fbl is None


# =========================================================================
# Type 2 — Handshake
# =========================================================================

class TestType2Handshake:
    """Test HidDeviceType2.handshake() orchestration."""

    def test_successful_handshake(self):
        transport = _make_mock_transport()
        transport.read.return_value = _make_type2_valid_response()
        transport.write.return_value = TYPE2_INIT_SIZE

        dev = HidDeviceType2(transport)
        info = dev.handshake()

        assert info.device_type == 2
        assert dev._initialized is True
        transport.write.assert_called_once()
        transport.read.assert_called_once()

    def test_handshake_sends_correct_packet(self):
        transport = _make_mock_transport()
        transport.read.return_value = _make_type2_valid_response()
        transport.write.return_value = TYPE2_INIT_SIZE

        dev = HidDeviceType2(transport)
        dev.handshake()

        write_args = transport.write.call_args
        assert write_args[0][0] == EP_WRITE_02  # endpoint
        assert len(write_args[0][1]) == TYPE2_INIT_SIZE  # packet size

    def test_handshake_reads_from_ep01(self):
        transport = _make_mock_transport()
        transport.read.return_value = _make_type2_valid_response()
        transport.write.return_value = TYPE2_INIT_SIZE

        dev = HidDeviceType2(transport)
        dev.handshake()

        read_args = transport.read.call_args
        assert read_args[0][0] == EP_READ_01
        assert read_args[0][1] == TYPE2_RESPONSE_SIZE

    def test_handshake_failure_raises(self):
        transport = _make_mock_transport()
        transport.read.return_value = b'\x00' * TYPE2_RESPONSE_SIZE  # bad magic

        dev = HidDeviceType2(transport)
        with pytest.raises(RuntimeError, match="handshake failed"):
            dev.handshake()

        assert dev._initialized is False

    def test_handshake_stores_device_info(self):
        transport = _make_mock_transport()
        resp = bytearray(_make_type2_valid_response())
        resp[4] = 0x42
        resp[5] = 0x99
        transport.read.return_value = bytes(resp)
        transport.write.return_value = TYPE2_INIT_SIZE

        dev = HidDeviceType2(transport)
        info = dev.handshake()

        assert dev.device_info is info
        assert info.mode_byte_1 == 0x42
        assert info.mode_byte_2 == 0x99


# =========================================================================
# Type 2 — Frame Send
# =========================================================================

class TestType2FrameSend:
    """Test HidDeviceType2 frame construction and sending."""

    def _init_device(self) -> tuple:
        """Helper: create initialized Type 2 device."""
        transport = _make_mock_transport()
        transport.read.return_value = _make_type2_valid_response()
        transport.write.return_value = 512
        dev = HidDeviceType2(transport)
        dev.handshake()
        transport.reset_mock()
        transport.write.return_value = 512
        return dev, transport

    def test_frame_packet_header(self):
        """Verify 20-byte header has correct size field."""
        data = b'\xFF' * 1000
        pkt = HidDeviceType2.build_frame_packet(data)
        # bytes[16:20] = LE uint32 of data length
        size_field = struct.unpack('<I', pkt[16:20])[0]
        assert size_field == 1000

    def test_frame_packet_alignment(self):
        """Packet length is always a multiple of 512."""
        for data_len in [0, 1, 100, 492, 493, 1000, 5000]:
            data = b'\xAA' * data_len
            pkt = HidDeviceType2.build_frame_packet(data)
            assert len(pkt) % USB_BULK_ALIGNMENT == 0

    def test_frame_packet_contains_data(self):
        """Image data starts at offset 20."""
        data = b'\xDE\xAD\xBE\xEF'
        pkt = HidDeviceType2.build_frame_packet(data)
        assert pkt[20:24] == data

    def test_frame_packet_zero_padding(self):
        """Padding after data should be zeros."""
        data = b'\xFF' * 10
        pkt = HidDeviceType2.build_frame_packet(data)
        # After header (20) + data (10) = 30 bytes, rest should be zeros
        assert pkt[30:] == b'\x00' * (len(pkt) - 30)

    def test_frame_packet_exact_boundary(self):
        """Data that makes raw size exactly 512 stays at 512."""
        data = b'\xAA' * 492  # 20 + 492 = 512 exactly
        pkt = HidDeviceType2.build_frame_packet(data)
        assert len(pkt) == 512

    def test_frame_packet_one_over_boundary(self):
        """Data that makes raw size 513 rounds up to 1024."""
        data = b'\xAA' * 493  # 20 + 493 = 513
        pkt = HidDeviceType2.build_frame_packet(data)
        assert len(pkt) == 1024

    def test_send_frame_calls_write(self):
        dev, transport = self._init_device()
        dev.send_frame(b'\xFF' * 100)
        transport.write.assert_called_once()

    def test_send_frame_returns_true(self):
        dev, transport = self._init_device()
        assert dev.send_frame(b'\xFF' * 100) is True

    def test_send_frame_returns_false_on_zero_transfer(self):
        dev, transport = self._init_device()
        transport.write.return_value = 0
        assert dev.send_frame(b'\xFF' * 100) is False

    def test_send_frame_without_init_raises(self):
        transport = _make_mock_transport()
        dev = HidDeviceType2(transport)
        with pytest.raises(RuntimeError, match="not initialized"):
            dev.send_frame(b'\xFF')

    def test_send_frame_empty_data(self):
        dev, transport = self._init_device()
        result = dev.send_frame(b'')
        assert result is True
        pkt = transport.write.call_args[0][1]
        assert len(pkt) == 512  # 20-byte header rounds to 512
        assert struct.unpack('<I', pkt[16:20])[0] == 0


# =========================================================================
# Type 3 — Init Packet
# =========================================================================

class TestType3InitPacket:
    """Test HidDeviceType3.build_init_packet() exact bytes."""

    def test_packet_length(self):
        pkt = HidDeviceType3.build_init_packet()
        assert len(pkt) == TYPE3_INIT_SIZE  # 1040

    def test_prefix_bytes(self):
        pkt = HidDeviceType3.build_init_packet()
        expected = bytes([
            0xF5, 0x00, 0x01, 0x00,
            0xBC, 0xFF, 0xB6, 0xC8,
            0x00, 0x00, 0x00, 0x00,
            0x00, 0x04, 0x00, 0x00,
        ])
        assert pkt[:16] == expected

    def test_padding_is_zeros(self):
        pkt = HidDeviceType3.build_init_packet()
        assert pkt[16:] == b'\x00' * 1024

    def test_total_is_prefix_plus_padding(self):
        pkt = HidDeviceType3.build_init_packet()
        assert len(pkt) == 16 + 1024


# =========================================================================
# Type 3 — Response Validation
# =========================================================================

class TestType3ResponseValidation:
    """Test HidDeviceType3.validate_response()."""

    def test_valid_0x65(self):
        resp = _make_type3_valid_response(0x65)
        assert HidDeviceType3.validate_response(resp) is True

    def test_valid_0x66(self):
        resp = _make_type3_valid_response(0x66)
        assert HidDeviceType3.validate_response(resp) is True

    def test_invalid_first_byte(self):
        resp = _make_type3_valid_response()
        resp = b'\x64' + resp[1:]  # 0x64 = 100, not valid
        assert HidDeviceType3.validate_response(resp) is False

    def test_invalid_0x67(self):
        resp = b'\x67' + b'\x00' * (TYPE3_RESPONSE_SIZE - 1)
        assert HidDeviceType3.validate_response(resp) is False

    def test_zero_first_byte(self):
        resp = b'\x00' * TYPE3_RESPONSE_SIZE
        assert HidDeviceType3.validate_response(resp) is False

    def test_short_response(self):
        assert HidDeviceType3.validate_response(b'\x65') is False

    def test_empty_response(self):
        assert HidDeviceType3.validate_response(b'') is False


# =========================================================================
# Type 3 — Device Info Parsing
# =========================================================================

class TestType3DeviceInfo:
    """Test HidDeviceType3.parse_device_info()."""

    def test_fbl_from_0x65(self):
        resp = _make_type3_valid_response(0x65)
        info = HidDeviceType3.parse_device_info(resp)
        assert info.fbl == 100  # 0x65 - 1

    def test_fbl_from_0x66(self):
        resp = _make_type3_valid_response(0x66)
        info = HidDeviceType3.parse_device_info(resp)
        assert info.fbl == 101  # 0x66 - 1

    def test_serial_extraction(self):
        resp = bytearray(TYPE3_RESPONSE_SIZE)
        resp[0] = 0x65
        resp[10:14] = b'\xCA\xFE\xBA\xBE'
        info = HidDeviceType3.parse_device_info(bytes(resp))
        assert info.serial == "CAFEBABE"

    def test_device_type_is_3(self):
        resp = _make_type3_valid_response()
        info = HidDeviceType3.parse_device_info(resp)
        assert info.device_type == 3

    def test_mode_byte_1_equals_fbl(self):
        resp = _make_type3_valid_response(0x66)
        info = HidDeviceType3.parse_device_info(resp)
        assert info.mode_byte_1 == info.fbl == 101


# =========================================================================
# Type 3 — Handshake
# =========================================================================

class TestType3Handshake:
    """Test HidDeviceType3.handshake() orchestration."""

    def test_successful_handshake(self):
        transport = _make_mock_transport()
        transport.read.return_value = _make_type3_valid_response()
        transport.write.return_value = TYPE3_INIT_SIZE

        dev = HidDeviceType3(transport)
        info = dev.handshake()

        assert info.device_type == 3
        assert dev._initialized is True

    def test_handshake_sends_correct_packet(self):
        transport = _make_mock_transport()
        transport.read.return_value = _make_type3_valid_response()
        transport.write.return_value = TYPE3_INIT_SIZE

        dev = HidDeviceType3(transport)
        dev.handshake()

        write_args = transport.write.call_args
        assert write_args[0][0] == EP_WRITE_02
        assert len(write_args[0][1]) == TYPE3_INIT_SIZE

    def test_handshake_reads_1024(self):
        transport = _make_mock_transport()
        transport.read.return_value = _make_type3_valid_response()
        transport.write.return_value = TYPE3_INIT_SIZE

        dev = HidDeviceType3(transport)
        dev.handshake()

        read_args = transport.read.call_args
        assert read_args[0][0] == EP_READ_01
        assert read_args[0][1] == TYPE3_RESPONSE_SIZE

    def test_handshake_failure_raises(self):
        transport = _make_mock_transport()
        transport.read.return_value = b'\x00' * TYPE3_RESPONSE_SIZE

        dev = HidDeviceType3(transport)
        with pytest.raises(RuntimeError, match="handshake failed"):
            dev.handshake()

        assert dev._initialized is False

    def test_handshake_stores_device_info(self):
        transport = _make_mock_transport()
        transport.read.return_value = _make_type3_valid_response(0x66)
        transport.write.return_value = TYPE3_INIT_SIZE

        dev = HidDeviceType3(transport)
        info = dev.handshake()

        assert dev.device_info is info
        assert info.fbl == 101


# =========================================================================
# Type 3 — Frame Send
# =========================================================================

class TestType3FrameSend:
    """Test HidDeviceType3 frame construction and sending."""

    def _init_device(self) -> tuple:
        """Helper: create initialized Type 3 device."""
        transport = _make_mock_transport()
        transport.read.return_value = _make_type3_valid_response()
        transport.write.return_value = TYPE3_INIT_SIZE
        dev = HidDeviceType3(transport)
        dev.handshake()
        transport.reset_mock()
        transport.write.return_value = TYPE3_FRAME_TOTAL
        transport.read.return_value = b'\x00' * TYPE3_ACK_SIZE
        return dev, transport

    def test_frame_packet_total_length(self):
        pkt = HidDeviceType3.build_frame_packet(b'\xFF' * 1000)
        assert len(pkt) == TYPE3_FRAME_TOTAL  # 204816

    def test_frame_packet_prefix(self):
        pkt = HidDeviceType3.build_frame_packet(b'\xFF' * 100)
        expected_prefix = bytes([
            0xF5, 0x01, 0x01, 0x00,
            0xBC, 0xFF, 0xB6, 0xC8,
            0x00, 0x00, 0x00, 0x00,
            0x00, 0x20, 0x03, 0x00,   # 204800 LE
        ])
        assert pkt[:16] == expected_prefix

    def test_frame_packet_size_field(self):
        """bytes[12:16] should encode 204800 as LE uint32."""
        pkt = HidDeviceType3.build_frame_packet(b'')
        size = struct.unpack('<I', pkt[12:16])[0]
        assert size == TYPE3_DATA_SIZE  # 204800

    def test_frame_packet_data_padded(self):
        """Short data is zero-padded to 204800."""
        data = b'\xAB' * 100
        pkt = HidDeviceType3.build_frame_packet(data)
        assert pkt[16:116] == data
        assert pkt[116:] == b'\x00' * (TYPE3_DATA_SIZE - 100)

    def test_frame_packet_data_truncated(self):
        """Oversized data is truncated to 204800."""
        data = b'\xAB' * (TYPE3_DATA_SIZE + 500)
        pkt = HidDeviceType3.build_frame_packet(data)
        assert len(pkt) == TYPE3_FRAME_TOTAL
        assert pkt[16:] == data[:TYPE3_DATA_SIZE]

    def test_frame_packet_exact_size_data(self):
        """Exactly 204800 bytes of data — no padding or truncation."""
        data = b'\xCC' * TYPE3_DATA_SIZE
        pkt = HidDeviceType3.build_frame_packet(data)
        assert len(pkt) == TYPE3_FRAME_TOTAL
        assert pkt[16:] == data

    def test_send_frame_writes_then_reads_ack(self):
        dev, transport = self._init_device()
        dev.send_frame(b'\xFF' * 100)

        # Should write frame, then read ACK
        assert transport.write.call_count == 1
        assert transport.read.call_count == 1

    def test_send_frame_write_endpoint(self):
        dev, transport = self._init_device()
        dev.send_frame(b'\xFF' * 100)
        assert transport.write.call_args[0][0] == EP_WRITE_02

    def test_send_frame_ack_read(self):
        dev, transport = self._init_device()
        dev.send_frame(b'\xFF' * 100)
        read_args = transport.read.call_args
        assert read_args[0][0] == EP_READ_01
        assert read_args[0][1] == TYPE3_ACK_SIZE

    def test_send_frame_returns_true(self):
        dev, transport = self._init_device()
        assert dev.send_frame(b'\xFF' * 100) is True

    def test_send_frame_returns_false_on_zero_write(self):
        dev, transport = self._init_device()
        transport.write.return_value = 0
        assert dev.send_frame(b'\xFF' * 100) is False

    def test_send_frame_returns_false_on_empty_ack(self):
        dev, transport = self._init_device()
        transport.read.return_value = b''
        assert dev.send_frame(b'\xFF' * 100) is False

    def test_send_frame_without_init_raises(self):
        transport = _make_mock_transport()
        dev = HidDeviceType3(transport)
        with pytest.raises(RuntimeError, match="not initialized"):
            dev.send_frame(b'\xFF')


# =========================================================================
# send_image_to_hid_device — public API
# =========================================================================

class TestSendImageToHidDevice:
    """Test the high-level public API."""

    def setup_method(self):
        """Clear global state between tests."""
        import trcc.hid_device as mod
        mod._initialized_transports.clear()
        mod._device_handlers.clear()

    def test_type2_first_call_does_handshake(self):
        transport = _make_mock_transport()
        transport.read.return_value = _make_type2_valid_response()
        transport.write.return_value = 512

        result = send_image_to_hid_device(transport, b'\xFF' * 100, device_type=2)
        assert result is True
        # 1 write for init + 1 write for frame
        assert transport.write.call_count == 2

    def test_type2_second_call_skips_handshake(self):
        transport = _make_mock_transport()
        transport.read.return_value = _make_type2_valid_response()
        transport.write.return_value = 512

        send_image_to_hid_device(transport, b'\xFF' * 100, device_type=2)
        transport.reset_mock()
        transport.write.return_value = 512

        send_image_to_hid_device(transport, b'\xAA' * 100, device_type=2)
        # Only 1 write (frame), no handshake
        assert transport.write.call_count == 1

    def test_type3_first_call_does_handshake(self):
        transport = _make_mock_transport()
        transport.read.return_value = _make_type3_valid_response()
        transport.write.return_value = TYPE3_FRAME_TOTAL

        result = send_image_to_hid_device(transport, b'\xFF' * 100, device_type=3)
        assert result is True
        # 1 write for init + 1 write for frame
        assert transport.write.call_count == 2

    def test_type3_second_call_skips_handshake(self):
        transport = _make_mock_transport()
        # First call: handshake response, then ACK for frame
        transport.read.side_effect = [
            _make_type3_valid_response(),  # handshake
            b'\x00' * TYPE3_ACK_SIZE,      # frame ACK
        ]
        transport.write.return_value = TYPE3_FRAME_TOTAL

        send_image_to_hid_device(transport, b'\xFF' * 100, device_type=3)
        transport.reset_mock()
        transport.write.return_value = TYPE3_FRAME_TOTAL
        transport.read.return_value = b'\x00' * TYPE3_ACK_SIZE

        send_image_to_hid_device(transport, b'\xAA' * 100, device_type=3)
        assert transport.write.call_count == 1  # frame only

    def test_invalid_device_type(self):
        transport = _make_mock_transport()
        result = send_image_to_hid_device(transport, b'\xFF', device_type=99)
        assert result is False

    def test_handshake_failure_returns_false(self):
        transport = _make_mock_transport()
        transport.read.return_value = b'\x00' * TYPE2_RESPONSE_SIZE  # bad response
        transport.write.return_value = 512

        result = send_image_to_hid_device(transport, b'\xFF' * 100, device_type=2)
        assert result is False

    def test_handshake_failure_allows_retry(self):
        """After a failed handshake, the next call should try again."""
        transport = _make_mock_transport()
        bad_resp = b'\x00' * TYPE2_RESPONSE_SIZE
        good_resp = _make_type2_valid_response()

        transport.read.side_effect = [bad_resp, good_resp]
        transport.write.return_value = 512

        # First call fails
        result1 = send_image_to_hid_device(transport, b'\xFF', device_type=2)
        assert result1 is False

        # Second call retries handshake and succeeds
        result2 = send_image_to_hid_device(transport, b'\xFF', device_type=2)
        assert result2 is True

    def test_write_exception_returns_false(self):
        transport = _make_mock_transport()
        transport.write.side_effect = OSError("USB disconnected")

        result = send_image_to_hid_device(transport, b'\xFF', device_type=2)
        assert result is False


# =========================================================================
# DeviceInfo dataclass
# =========================================================================

class TestDeviceInfo:
    """Test DeviceInfo dataclass fields and defaults."""

    def test_defaults(self):
        info = DeviceInfo(device_type=2)
        assert info.device_type == 2
        assert info.mode_byte_1 == 0
        assert info.mode_byte_2 == 0
        assert info.serial == ""
        assert info.fbl is None

    def test_type3_with_fbl(self):
        info = DeviceInfo(device_type=3, fbl=100, serial="DEADBEEF")
        assert info.fbl == 100
        assert info.serial == "DEADBEEF"


# =========================================================================
# Constants sanity checks
# =========================================================================

class TestConstants:
    """Verify constants match the C# source values."""

    def test_type2_vid_pid(self):
        assert TYPE2_VID == 0x0416
        assert TYPE2_PID == 0x530A

    def test_type3_vid_pid(self):
        assert TYPE3_VID == 0x0416
        assert TYPE3_PID == 0x53E6

    def test_type2_magic(self):
        assert TYPE2_MAGIC == bytes([0xDA, 0xDB, 0xDC, 0xDD])

    def test_type3_cmd_prefix(self):
        assert TYPE3_CMD_PREFIX == bytes([0xF5, 0x00, 0x01, 0x00, 0xBC, 0xFF, 0xB6, 0xC8])

    def test_type3_frame_prefix(self):
        assert TYPE3_FRAME_PREFIX == bytes([0xF5, 0x01, 0x01, 0x00, 0xBC, 0xFF, 0xB6, 0xC8])

    def test_type3_data_size(self):
        assert TYPE3_DATA_SIZE == 320 * 320 * 2  # RGB565

    def test_type3_frame_total(self):
        assert TYPE3_FRAME_TOTAL == 16 + TYPE3_DATA_SIZE

    def test_type3_init_size(self):
        assert TYPE3_INIT_SIZE == 16 + 1024
