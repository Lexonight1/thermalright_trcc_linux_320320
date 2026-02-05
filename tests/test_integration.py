#!/usr/bin/env python3
"""
Integration test - verifies all core components work together.
Quick smoke test to ensure the OOP architecture is functional.
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import (
    EventBus,
    ThemeManager,
    ButtonFactory,
    ImageMode,
    VideoMode,
    Theme
)
from PIL import Image


def test_integration():
    """Integration test - all components working together."""
    print("Running Integration Test...")
    print("=" * 60)

    # Test 1: EventBus
    print("\n[1] Testing EventBus...")
    event_bus = EventBus()
    events_received = []

    def handler(data):
        events_received.append(data)

    event_bus.subscribe('test', handler)
    event_bus.publish('test', 'hello')

    assert len(events_received) == 1, "EventBus failed"
    print("    ✓ EventBus works")

    # Test 2: ThemeManager (Singleton)
    print("\n[2] Testing ThemeManager...")
    tm1 = ThemeManager()
    tm2 = ThemeManager()

    assert tm1 is tm2, "ThemeManager not singleton"
    print("    ✓ ThemeManager singleton works")

    # Test 3: Theme dataclass
    print("\n[3] Testing Theme dataclass...")
    theme = Theme(
        name='TestTheme',
        path='/test',
        theme_type='local',
        preview_image='/test/preview.png'
    )

    assert theme.name == 'TestTheme', "Theme creation failed"
    assert len(theme.background_images) == 0, "Theme background_images not initialized"
    print("    ✓ Theme dataclass works")

    # Test 4: ImageMode
    print("\n[4] Testing ImageMode...")
    image_mode = ImageMode()
    test_image = Image.new('RGB', (320, 320), color='red')

    image_mode.set_image(test_image)
    frame = image_mode.get_frame()

    assert frame is not None, "ImageMode failed"
    assert frame.size == (320, 320), "ImageMode size wrong"
    print("    ✓ ImageMode works")

    # Test 5: VideoMode
    print("\n[5] Testing VideoMode...")
    video_mode = VideoMode()

    video_mode.play()
    assert video_mode.is_playing, "VideoMode play failed"

    video_mode.pause()
    assert not video_mode.is_playing, "VideoMode pause failed"
    print("    ✓ VideoMode works")

    # Test 6: Components working together
    print("\n[6] Testing components integration...")

    # Create theme and publish event
    theme2 = Theme(name='Theme2', path='/test2', theme_type='cloud')
    tm1.themes['Theme2'] = theme2

    theme_changed = []

    def on_theme_change(theme):
        theme_changed.append(theme)

    event_bus.subscribe('theme_changed', on_theme_change)

    # Load theme
    loaded_theme = tm1.load_theme('Theme2')
    event_bus.publish('theme_changed', loaded_theme)

    assert len(theme_changed) == 1, "Integration failed"
    assert theme_changed[0].name == 'Theme2', "Integration data wrong"
    print("    ✓ Components integrate properly")

    print("\n" + "=" * 60)
    print("✓ All integration tests passed!")
    print("=" * 60)

    return True


if __name__ == '__main__':
    try:
        success = test_integration()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n✗ Integration test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
