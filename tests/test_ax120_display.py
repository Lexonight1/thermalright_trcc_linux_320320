"""Tests for unified segment display renderer (all LED styles 1-11).

Validates segment encoding, indicator LEDs, leading zero suppression,
rotation phases, style-specific layouts, and LEDService integration.
"""

from datetime import datetime
from unittest.mock import patch

import pytest

from trcc.device_led_segment import (
    DISPLAYS,
    AK120Display,
    AX120Display,
    CZ1Display,
    LC1Display,
    LC2Display,
    LF8Display,
    LF10Display,
    LF11Display,
    LF12Display,
    PA120Display,
    SegmentDisplay,
    compute_mask,
    get_display,
    has_segment_display,
)

# =========================================================================
# Base class — encoding tables
# =========================================================================

class TestSegmentEncoding:
    def test_7seg_table_has_digits_0_through_9(self):
        for d in '0123456789':
            assert d in SegmentDisplay.CHAR_7SEG

    def test_7seg_table_has_unit_symbols(self):
        for ch in ('C', 'F', 'H', 'G', ' '):
            assert ch in SegmentDisplay.CHAR_7SEG

    def test_7seg_wire_order(self):
        assert SegmentDisplay.WIRE_7SEG == ('a', 'b', 'c', 'd', 'e', 'f', 'g')

    def test_7seg_all_segments_valid(self):
        valid = {'a', 'b', 'c', 'd', 'e', 'f', 'g'}
        for ch, segs in SegmentDisplay.CHAR_7SEG.items():
            assert segs.issubset(valid), f"'{ch}' has invalid segments"

    def test_13seg_table_has_digits_0_through_9(self):
        for d in '0123456789':
            assert d in SegmentDisplay.CHAR_13SEG

    def test_13seg_wire_order_length(self):
        assert len(SegmentDisplay.WIRE_13SEG) == 13

    def test_digit_8_has_all_7_segments(self):
        assert SegmentDisplay.CHAR_7SEG['8'] == {'a', 'b', 'c', 'd', 'e', 'f', 'g'}

    def test_digit_1_has_bc_only(self):
        assert SegmentDisplay.CHAR_7SEG['1'] == {'b', 'c'}

    def test_space_is_blank(self):
        assert SegmentDisplay.CHAR_7SEG[' '] == set()

    def test_13seg_0_is_blank(self):
        """13-seg '0' = blank (leading zero suppression for hundreds)."""
        assert SegmentDisplay.CHAR_13SEG['0'] == set()


# =========================================================================
# Registry
# =========================================================================

class TestRegistry:
    def test_all_styles_registered(self):
        for s in range(1, 12):
            assert s in DISPLAYS

    def test_style_12_not_registered(self):
        assert 12 not in DISPLAYS

    def test_style_13_not_registered(self):
        assert 13 not in DISPLAYS

    def test_compute_mask_returns_list(self):
        mask = compute_mask(1, {'cpu_temp': 50})
        assert isinstance(mask, list)
        assert all(isinstance(b, bool) for b in mask)

    def test_compute_mask_unknown_style(self):
        assert compute_mask(99, {}) == []

    def test_get_display_returns_instance(self):
        d = get_display(1)
        assert isinstance(d, AX120Display)

    def test_get_display_none_for_unknown(self):
        assert get_display(99) is None

    def test_has_segment_display(self):
        for s in range(1, 12):
            assert has_segment_display(s) is True
        assert has_segment_display(12) is False
        assert has_segment_display(13) is False

    def test_style_11_uses_lf8_layout(self):
        assert isinstance(DISPLAYS[11], LF8Display)

    @pytest.mark.parametrize("style_id,expected_type", [
        (1, AX120Display), (2, PA120Display), (3, AK120Display),
        (4, LC1Display), (5, LF8Display), (6, LF12Display),
        (7, LF10Display), (8, CZ1Display), (9, LC2Display),
        (10, LF11Display),
    ])
    def test_display_types(self, style_id, expected_type):
        assert isinstance(DISPLAYS[style_id], expected_type)


# =========================================================================
# Style 1 — AX120_DIGITAL (30 LEDs, 3 digits, 4-phase)
# =========================================================================

class TestAX120Display:
    def setup_method(self):
        self.d = AX120Display()

    def test_mask_size(self):
        assert self.d.mask_size == 30

    def test_phase_count(self):
        assert self.d.phase_count == 4

    def test_returns_30_bools(self):
        mask = self.d.compute_mask({'cpu_temp': 42}, 0, "C")
        assert len(mask) == 30

    def test_always_on_leds(self):
        mask = self.d.compute_mask({}, 0, "C")
        assert mask[0] is True
        assert mask[1] is True

    def test_cpu_temp_phase(self):
        mask = self.d.compute_mask({'cpu_temp': 55}, 0, "C")
        assert mask[2] is True   # CPU1
        assert mask[3] is True   # CPU2
        assert mask[4] is False  # GPU1
        assert mask[5] is False  # GPU2
        assert mask[6] is True   # °C
        assert mask[7] is False  # °F
        assert mask[8] is False  # %

    def test_cpu_usage_phase(self):
        mask = self.d.compute_mask({'cpu_percent': 80}, 1, "C")
        assert mask[2] is True   # CPU
        assert mask[8] is True   # %
        assert mask[6] is False  # °C

    def test_gpu_temp_phase(self):
        mask = self.d.compute_mask({'gpu_temp': 70}, 2, "C")
        assert mask[4] is True   # GPU1
        assert mask[5] is True   # GPU2
        assert mask[2] is False  # CPU1
        assert mask[6] is True   # °C

    def test_gpu_usage_phase(self):
        mask = self.d.compute_mask({'gpu_usage': 50}, 3, "C")
        assert mask[4] is True   # GPU
        assert mask[8] is True   # %

    def test_fahrenheit_indicator(self):
        mask = self.d.compute_mask({'cpu_temp': 72}, 0, "F")
        assert mask[7] is True   # °F
        assert mask[6] is False  # °C

    @pytest.mark.parametrize("digit,expected_segs", [
        (0, {'a', 'b', 'c', 'd', 'e', 'f'}),
        (1, {'b', 'c'}),
        (5, {'a', 'c', 'd', 'f', 'g'}),
        (8, {'a', 'b', 'c', 'd', 'e', 'f', 'g'}),
    ])
    def test_ones_digit_encoding(self, digit, expected_segs):
        mask = self.d.compute_mask({'cpu_temp': digit}, 0, "C")
        wire = self.d.WIRE_7SEG
        ones_leds = self.d.DIGITS[2]
        for wi, seg in enumerate(wire):
            assert mask[ones_leds[wi]] is (seg in expected_segs)

    def test_leading_zero_suppression_value_0(self):
        mask = self.d.compute_mask({'cpu_temp': 0}, 0, "C")
        for led in self.d.DIGITS[0]:
            assert mask[led] is False
        for led in self.d.DIGITS[1]:
            assert mask[led] is False

    def test_leading_zero_suppression_value_5(self):
        mask = self.d.compute_mask({'cpu_temp': 5}, 0, "C")
        for led in self.d.DIGITS[0]:
            assert mask[led] is False
        for led in self.d.DIGITS[1]:
            assert mask[led] is False

    def test_value_10_tens_shown(self):
        mask = self.d.compute_mask({'cpu_temp': 10}, 0, "C")
        for led in self.d.DIGITS[0]:
            assert mask[led] is False
        on_count = sum(1 for led in self.d.DIGITS[1] if mask[led])
        assert on_count == 2  # '1' = b,c

    def test_value_888_all_segments_lit(self):
        mask = self.d.compute_mask({'cpu_temp': 888}, 0, "C")
        for digit in self.d.DIGITS:
            for led in digit:
                assert mask[led] is True

    def test_clamped_to_999(self):
        m1 = self.d.compute_mask({'cpu_temp': 1500}, 0, "C")
        m2 = self.d.compute_mask({'cpu_temp': 999}, 0, "C")
        assert m1 == m2

    def test_negative_clamped_to_0(self):
        m1 = self.d.compute_mask({'cpu_temp': -10}, 0, "C")
        m2 = self.d.compute_mask({'cpu_temp': 0}, 0, "C")
        assert m1 == m2


# =========================================================================
# Style 2 — PA120_DIGITAL (84 LEDs, simultaneous, remap)
# =========================================================================

class TestPA120Display:
    def setup_method(self):
        self.d = PA120Display()

    def test_mask_size(self):
        assert self.d.mask_size == 84

    def test_phase_count(self):
        assert self.d.phase_count == 1

    def test_always_on_indicators(self):
        mask = self.d.compute_mask({}, 0, "C")
        for idx in (0, 1, 2, 3, 6, 9):  # CPU1,CPU2,GPU1,GPU2,BFB,BFB1
            assert mask[idx] is True

    def test_celsius_indicators(self):
        mask = self.d.compute_mask({}, 0, "C")
        assert mask[4] is True   # SSD (°C)
        assert mask[7] is True   # SSD1 (°C GPU)
        assert mask[5] is False  # HSD (°F)
        assert mask[8] is False  # HSD1 (°F GPU)

    def test_fahrenheit_indicators(self):
        mask = self.d.compute_mask({}, 0, "F")
        assert mask[5] is True   # HSD
        assert mask[8] is True   # HSD1
        assert mask[4] is False  # SSD
        assert mask[7] is False  # SSD1

    def test_simultaneous_all_metrics(self):
        metrics = {'cpu_temp': 65, 'cpu_percent': 80, 'gpu_temp': 70, 'gpu_usage': 50}
        mask = self.d.compute_mask(metrics, 0, "C")
        # cpuTemp digits should be lit (value 65)
        on_count = sum(1 for led in self.d.CPU_TEMP_DIGITS[2] if mask[led])
        assert on_count > 0

    def test_gpu_usage_partial(self):
        """GPU usage 100+ lights the partial indicator."""
        mask = self.d.compute_mask({'gpu_usage': 100}, 0, "C")
        assert mask[82] is True  # GPU_USE_PARTIAL[0]
        assert mask[83] is True  # GPU_USE_PARTIAL[1]

    def test_gpu_usage_under_100_no_partial(self):
        mask = self.d.compute_mask({'gpu_usage': 99}, 0, "C")
        assert mask[82] is False
        assert mask[83] is False


# =========================================================================
# Style 3 — AK120_DIGITAL (64 LEDs, 2-phase, remap)
# =========================================================================

class TestAK120Display:
    def setup_method(self):
        self.d = AK120Display()

    def test_mask_size(self):
        assert self.d.mask_size == 69

    def test_phase_count(self):
        assert self.d.phase_count == 2

    def test_cpu_phase(self):
        mask = self.d.compute_mask({'cpu_temp': 50, 'cpu_percent': 75, 'cpu_watt': 120}, 0, "C")
        assert mask[0] is True   # CPU1
        assert mask[5] is False  # GPU1
        assert mask[1] is True   # WATT always on
        assert mask[4] is True   # BFB always on

    def test_gpu_phase(self):
        mask = self.d.compute_mask({'gpu_temp': 60, 'gpu_usage': 90, 'gpu_watt': 200}, 1, "C")
        assert mask[5] is True   # GPU1
        assert mask[0] is False  # CPU1

    def test_temp_unit_indicator(self):
        mask_c = self.d.compute_mask({}, 0, "C")
        assert mask_c[2] is True   # SSD (°C)
        assert mask_c[3] is False  # HSD (°F)
        mask_f = self.d.compute_mask({}, 0, "F")
        assert mask_f[3] is True
        assert mask_f[2] is False

    def test_usage_partial(self):
        mask = self.d.compute_mask({'cpu_percent': 100}, 0, "C")
        assert mask[62] is True  # USE_PARTIAL[0]
        assert mask[63] is True  # USE_PARTIAL[1]


# =========================================================================
# Style 4 — LC1 (31 LEDs, mode-based 3-phase, remap)
# =========================================================================

class TestLC1Display:
    def setup_method(self):
        self.d = LC1Display()

    def test_mask_size(self):
        assert self.d.mask_size == 38

    def test_phase_count(self):
        assert self.d.phase_count == 3

    def test_temp_phase(self):
        mask = self.d.compute_mask({'mem_temp': 45}, 0, "C")
        assert mask[0] is True  # SSD indicator
        assert mask[1] is False  # MTNO
        assert mask[2] is False  # GNO

    def test_mhz_phase(self):
        mask = self.d.compute_mask({'mem_clock': 3200}, 1, "C")
        assert mask[1] is True   # MTNO
        assert mask[0] is False  # SSD

    def test_gb_phase(self):
        mask = self.d.compute_mask({'mem_used': 16}, 2, "C")
        assert mask[2] is True   # GNO
        assert mask[0] is False  # SSD

    def test_unit_digit_celsius(self):
        """Phase 0 with °C should encode 'C' in unit digit."""
        mask = self.d.compute_mask({'mem_temp': 45}, 0, "C")
        segs_c = SegmentDisplay.CHAR_7SEG['C']
        wire = self.d.WIRE_7SEG
        unit_leds = self.d.UNIT_DIGIT
        for wi, seg in enumerate(wire):
            assert mask[unit_leds[wi]] is (seg in segs_c)

    def test_unit_digit_fahrenheit(self):
        mask = self.d.compute_mask({'mem_temp': 45}, 0, "F")
        segs_f = SegmentDisplay.CHAR_7SEG['F']
        wire = self.d.WIRE_7SEG
        unit_leds = self.d.UNIT_DIGIT
        for wi, seg in enumerate(wire):
            assert mask[unit_leds[wi]] is (seg in segs_f)

    def test_fahrenheit_conversion(self):
        """°F phase should convert °C value to °F."""
        mask_c = self.d.compute_mask({'mem_temp': 100}, 0, "C")
        mask_f = self.d.compute_mask({'mem_temp': 100}, 0, "F")
        # 100°C = 212°F → different digits → different masks
        assert mask_c != mask_f


# =========================================================================
# Style 5 — LF8 (93 LEDs, 4-metric, 2-phase)
# =========================================================================

class TestLF8Display:
    def setup_method(self):
        self.d = LF8Display()

    def test_mask_size(self):
        assert self.d.mask_size == 93

    def test_phase_count(self):
        assert self.d.phase_count == 2

    def test_always_on_indicators(self):
        mask = self.d.compute_mask({}, 0, "C")
        assert mask[4] is True  # WATT
        assert mask[5] is True  # MHZ
        assert mask[6] is True  # BFB

    def test_cpu_phase(self):
        mask = self.d.compute_mask({}, 0, "C")
        assert mask[0] is True   # CPU1
        assert mask[1] is False  # GPU1

    def test_gpu_phase(self):
        mask = self.d.compute_mask({}, 1, "C")
        assert mask[1] is True   # GPU1
        assert mask[0] is False  # CPU1

    def test_use_partial(self):
        mask = self.d.compute_mask({'cpu_percent': 100}, 0, "C")
        assert mask[91] is True  # USE_PARTIAL[0]
        assert mask[92] is True  # USE_PARTIAL[1]

    def test_4_metrics_encoded(self):
        """All 4 metrics should produce non-zero digit masks."""
        metrics = {'cpu_temp': 55, 'cpu_watt': 120, 'cpu_mhz': 3500, 'cpu_percent': 75}
        mask = self.d.compute_mask(metrics, 0, "C")
        for digits in (self.d.TEMP_DIGITS, self.d.WATT_DIGITS, self.d.MHZ_DIGITS):
            on_any = any(mask[led] for digit in digits for led in digit)
            assert on_any is True


# =========================================================================
# Style 6 — LF12 (124 LEDs = LF8 + decoration)
# =========================================================================

class TestLF12Display:
    def setup_method(self):
        self.d = LF12Display()

    def test_mask_size(self):
        assert self.d.mask_size == 124

    def test_inherits_lf8(self):
        assert isinstance(self.d, LF8Display)

    def test_decoration_always_on(self):
        mask = self.d.compute_mask({}, 0, "C")
        for idx in range(93, 124):
            assert mask[idx] is True

    def test_digit_region_same_as_lf8(self):
        """First 93 LEDs should have same digit encoding as LF8."""
        metrics = {'cpu_temp': 65, 'cpu_watt': 100, 'cpu_mhz': 2000, 'cpu_percent': 50}
        lf8 = LF8Display()
        mask_lf8 = lf8.compute_mask(metrics, 0, "C")
        mask_lf12 = self.d.compute_mask(metrics, 0, "C")
        assert mask_lf12[:93] == mask_lf8[:93]


# =========================================================================
# Style 7 — LF10 (116 LEDs, 13-segment + decoration)
# =========================================================================

class TestLF10Display:
    def setup_method(self):
        self.d = LF10Display()

    def test_mask_size(self):
        assert self.d.mask_size == 116

    def test_phase_count(self):
        assert self.d.phase_count == 1

    def test_indicators(self):
        mask = self.d.compute_mask({'cpu_temp': 50, 'gpu_temp': 60}, 0, "C")
        assert mask[0] is True  # CPU1
        assert mask[3] is True  # GPU1
        assert mask[1] is True  # SSD (°C CPU)
        assert mask[4] is True  # SSD1 (°C GPU)

    def test_fahrenheit_indicators(self):
        mask = self.d.compute_mask({}, 0, "F")
        assert mask[2] is True  # HSD
        assert mask[5] is True  # HSD1
        assert mask[1] is False  # SSD
        assert mask[4] is False  # SSD1

    def test_decoration_always_on(self):
        mask = self.d.compute_mask({}, 0, "C")
        for idx in range(84, 116):
            assert mask[idx] is True

    def test_13seg_digit_has_13_leds(self):
        for digit in self.d.DIGIT_LEDS_13:
            assert len(digit) == 13

    def test_cpu_temp_encoded(self):
        mask = self.d.compute_mask({'cpu_temp': 88}, 0, "C")
        # CPU digits (0-2) should have LEDs on
        on_any = any(mask[led] for digit in self.d.DIGIT_LEDS_13[:3] for led in digit)
        assert on_any is True

    def test_gpu_temp_encoded(self):
        mask = self.d.compute_mask({'gpu_temp': 75}, 0, "C")
        on_any = any(mask[led] for digit in self.d.DIGIT_LEDS_13[3:6] for led in digit)
        assert on_any is True

    def test_13seg_leading_zero_suppression(self):
        """Value < 100 should blank the 13-seg hundreds digit."""
        mask = self.d.compute_mask({'cpu_temp': 55}, 0, "C")
        # First 13 LEDs (hundreds digit) should all be off
        for led in self.d.DIGIT_LEDS_13[0]:
            assert mask[led] is False


# =========================================================================
# Style 8 — CZ1 (18 LEDs, 2 digits, 4-phase)
# =========================================================================

class TestCZ1Display:
    def setup_method(self):
        self.d = CZ1Display()

    def test_mask_size(self):
        assert self.d.mask_size == 18

    def test_phase_count(self):
        assert self.d.phase_count == 4

    def test_cpu_temp_phase(self):
        mask = self.d.compute_mask({'cpu_temp': 65}, 0, "C")
        assert mask[0] is True   # CPU1
        assert mask[1] is False  # GPU1

    def test_gpu_usage_phase(self):
        mask = self.d.compute_mask({'gpu_usage': 90}, 3, "C")
        assert mask[3] is True   # GPU2
        assert mask[0] is False  # CPU1

    def test_2digit_encoding(self):
        """CZ1 only has 2 digits — values > 99 clamped."""
        mask = self.d.compute_mask({'cpu_temp': 88}, 0, "C")
        for digit in self.d.DIGITS:
            # '8' lights all 7 segments
            for led in digit:
                assert mask[led] is True

    def test_leading_zero_suppression(self):
        mask = self.d.compute_mask({'cpu_temp': 5}, 0, "C")
        for led in self.d.DIGITS[0]:
            assert mask[led] is False  # tens = blank


# =========================================================================
# Style 9 — LC2 (61 LEDs, clock display)
# =========================================================================

class TestLC2Display:
    def setup_method(self):
        self.d = LC2Display()

    def test_mask_size(self):
        assert self.d.mask_size == 61

    def test_phase_count(self):
        assert self.d.phase_count == 1

    def test_decoration_always_on(self):
        mask = self.d.compute_mask({}, 0, "C")
        for idx in range(54, 61):
            assert mask[idx] is True

    @patch('trcc.device_led_segment.datetime')
    def test_24h_format(self, mock_dt):
        mock_dt.now.return_value = datetime(2024, 2, 14, 15, 30)
        mask = self.d.compute_mask({}, 0, "C", is_24h=True)
        # Hour tens = 1, hour ones = 5 → both should have lit segments
        on_tens = sum(1 for led in self.d.DIGITS[0] if mask[led])
        assert on_tens > 0

    @patch('trcc.device_led_segment.datetime')
    def test_12h_format(self, mock_dt):
        mock_dt.now.return_value = datetime(2024, 2, 14, 15, 30)
        mask = self.d.compute_mask({}, 0, "C", is_24h=False)
        # 15:00 in 12h = 3:00 → hour tens blank, hour ones = 3
        for led in self.d.DIGITS[0]:
            assert mask[led] is False  # hour tens = 0 → blank

    @patch('trcc.device_led_segment.datetime')
    def test_midnight_12h(self, mock_dt):
        mock_dt.now.return_value = datetime(2024, 2, 14, 0, 0)
        mask = self.d.compute_mask({}, 0, "C", is_24h=False)
        # 0:00 in 12h = 12:00 → hour tens = 1
        on_tens = sum(1 for led in self.d.DIGITS[0] if mask[led])
        assert on_tens > 0  # '1' has segments

    @patch('trcc.device_led_segment.datetime')
    def test_day_partial_bc(self, mock_dt):
        """Day ones digit uses partial (B,C segments only)."""
        mock_dt.now.return_value = datetime(2024, 2, 14, 12, 0)
        mask = self.d.compute_mask({}, 0, "C")
        # Day = 14 → ones = 4 → B,C in segs for '4'
        segs_4 = SegmentDisplay.CHAR_7SEG['4']
        if 'b' in segs_4:
            assert mask[52] is True  # DAY_ONES_BC[0]
        if 'c' in segs_4:
            assert mask[53] is True  # DAY_ONES_BC[1]


# =========================================================================
# Style 10 — LF11 (38 LEDs, 4-phase sensor)
# =========================================================================

class TestLF11Display:
    def setup_method(self):
        self.d = LF11Display()

    def test_mask_size(self):
        assert self.d.mask_size == 38

    def test_phase_count(self):
        assert self.d.phase_count == 4

    def test_cpu_temp_phase(self):
        mask = self.d.compute_mask({'cpu_temp': 65}, 0, "C")
        assert mask[0] is True   # SSD
        assert mask[1] is False  # BFB

    def test_cpu_usage_phase(self):
        mask = self.d.compute_mask({'cpu_percent': 80}, 1, "C")
        assert mask[1] is True   # BFB
        assert mask[0] is False  # SSD

    def test_unit_digit_on_temp_phase(self):
        """Temperature phases show unit symbol in digit 4."""
        mask = self.d.compute_mask({'cpu_temp': 50}, 0, "C")
        unit_leds = self.d.DIGITS[3]
        on_count = sum(1 for led in unit_leds if mask[led])
        assert on_count > 0

    def test_no_unit_digit_on_usage_phase(self):
        """Usage phases don't show unit symbol."""
        mask = self.d.compute_mask({'cpu_percent': 50}, 1, "C")
        unit_leds = self.d.DIGITS[3]
        on_count = sum(1 for led in unit_leds if mask[led])
        assert on_count == 0


# =========================================================================
# Cross-style consistency
# =========================================================================

class TestCrossStyleConsistency:
    def test_all_mask_sizes_correct(self):
        expected = {
            1: 30, 2: 84, 3: 69, 4: 38, 5: 93, 6: 124,
            7: 116, 8: 18, 9: 61, 10: 38, 11: 93,
        }
        for style_id, size in expected.items():
            d = get_display(style_id)
            assert d is not None
            assert d.mask_size == size, f"Style {style_id} mask_size"
            mask = d.compute_mask({}, 0, "C")
            assert len(mask) == size, f"Style {style_id} actual mask length"

    def test_all_masks_are_bool_lists(self):
        for style_id in range(1, 12):
            mask = compute_mask(style_id, {})
            assert all(isinstance(b, bool) for b in mask), f"Style {style_id}"

    def test_empty_metrics_no_crash(self):
        """All styles handle empty metrics gracefully."""
        for style_id in range(1, 12):
            mask = compute_mask(style_id, {})
            assert isinstance(mask, list)

    def test_all_phase_counts_positive(self):
        for style_id in range(1, 12):
            d = get_display(style_id)
            assert d is not None
            assert d.phase_count >= 1


# =========================================================================
# LEDService segment mode integration
# =========================================================================

class TestLEDServiceSegmentMode:
    def _make_service(self, style_id: int = 1):
        from trcc.services.led import LEDService
        svc = LEDService()
        svc.configure_for_style(style_id)
        svc._seg_display = get_display(style_id)
        svc._segment_mode = svc._seg_display is not None
        svc._seg_phase = 0
        svc._seg_tick_count = 0
        return svc

    def test_segment_mode_style_1(self):
        svc = self._make_service(1)
        assert svc._segment_mode is True
        assert isinstance(svc._seg_display, AX120Display)

    def test_segment_mode_style_5(self):
        svc = self._make_service(5)
        assert svc._segment_mode is True
        assert isinstance(svc._seg_display, LF8Display)

    def test_segment_mode_style_12_disabled(self):
        svc = self._make_service(12)
        assert svc._segment_mode is False

    def test_tick_advances_rotation(self):
        svc = self._make_service(1)
        svc._seg_phase_ticks = 5
        for _ in range(5):
            svc.tick()
        assert svc._seg_phase == 1

    def test_tick_wraps_at_phase_count(self):
        """Phase wraps using display's phase_count, not hardcoded 4."""
        svc = self._make_service(3)  # AK120: 2 phases
        svc._seg_phase_ticks = 1
        for _ in range(2):
            svc.tick()
        assert svc._seg_phase == 0  # Wrapped from 1 back to 0

    def test_tick_wraps_4_phase(self):
        svc = self._make_service(1)  # AX120: 4 phases
        svc._seg_phase_ticks = 1
        for _ in range(4):
            svc.tick()
        assert svc._seg_phase == 0

    def test_update_segment_mask(self):
        svc = self._make_service(1)
        svc.update_metrics({'cpu_temp': 65})
        svc._update_segment_mask()
        assert svc._segment_mask is not None
        assert len(svc._segment_mask) == 30

    def test_update_segment_mask_style_5(self):
        svc = self._make_service(5)
        svc.update_metrics({'cpu_temp': 65, 'cpu_watt': 100, 'cpu_mhz': 2000, 'cpu_percent': 50})
        svc._update_segment_mask()
        assert svc._segment_mask is not None
        assert len(svc._segment_mask) == 93

    def test_send_colors_uses_mask_length(self):
        """send_colors() should use mask length, not hardcoded AX120_LED_COUNT."""
        svc = self._make_service(5)  # 93 LEDs
        svc.update_metrics({'cpu_temp': 55})
        svc._update_segment_mask()

        sent = []

        class MockProtocol:
            def send_led_data(self, colors, is_on, global_on, brightness):
                sent.append((colors, is_on))
                return True

        svc.set_protocol(MockProtocol())
        svc.send_colors([(255, 0, 0)] * svc.state.segment_count)

        assert len(sent) == 1
        led_colors, is_on = sent[0]
        assert len(led_colors) == 93
        assert is_on is None

    def test_send_colors_applies_mask(self):
        svc = self._make_service(1)
        svc.update_metrics({'cpu_temp': 55})
        svc._update_segment_mask()
        mask = svc._segment_mask

        sent = []

        class MockProtocol:
            def send_led_data(self, colors, is_on, global_on, brightness):
                sent.append(colors)
                return True

        svc.set_protocol(MockProtocol())
        base_color = (255, 0, 0)
        svc.send_colors([base_color] * svc.state.segment_count)

        led_colors = sent[0]
        for i in range(30):
            if mask[i]:
                assert led_colors[i] == base_color
            else:
                assert led_colors[i] == (0, 0, 0)

    def test_hr10_mode_not_set_for_segment_styles(self):
        for style_id in range(1, 12):
            svc = self._make_service(style_id)
            assert svc._hr10_mode is False
