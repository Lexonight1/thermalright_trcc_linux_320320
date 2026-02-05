# TRCC Core Components - Test Suite

## Overview

Comprehensive unit tests for all core OOP components following best practices.

## Running Tests

### Quick Integration Test
```bash
python3 tests/test_integration.py
```

### Full Test Suite
```bash
python3 tests/run_tests.py
```

### Individual Test Files
```bash
python3 -m unittest tests/test_event_bus.py
python3 -m unittest tests/test_theme_manager.py
python3 -m unittest tests/test_display_modes.py
```

## Test Coverage

### test_event_bus.py (9 tests)
- ✓ Subscribe and publish
- ✓ Multiple subscribers
- ✓ Unsubscribe
- ✓ Exception handling in callbacks
- ✓ Clear events
- ✓ Subscriber count
- ✓ Duplicate subscription prevention

### test_theme_manager.py (10 tests)
- ✓ Singleton pattern
- ✓ Theme dataclass creation
- ✓ Scan local themes
- ✓ Load themes
- ✓ Filter themes by type
- ✓ Cache management

### test_display_modes.py (12 tests)
- ✓ ImageMode: set/get image, update
- ✓ VideoMode: play/pause/stop, frame advancement, looping
- ✓ ScreenMode: capture area, graceful failure

### test_gif_video.py (24 tests)
- ✓ GIFAnimator: load, frame navigation, loop, play/pause, reset, speed
- ✓ GIFThemeLoader: load theme, extract frames
- ✓ VideoPlayer: load, seek, progress, play/pause/stop, speed, extract
- ✓ Integration: compatible interfaces between GIF and Video players

### test_integration.py
- ✓ All components working together
- ✓ Event bus communication
- ✓ Theme management integration
- ✓ Display mode switching

## Test Results

```
======================================================================
Tests run: 54
Successes: 54
Failures: 0
Errors: 0
======================================================================
```

✓ **All tests passing**

## Test Structure

```
tests/
├── __init__.py              # Test package marker
├── README.md                # This file
├── run_tests.py             # Test runner (runs all tests)
├── test_integration.py      # Integration test (quick smoke test)
├── test_event_bus.py        # EventBus unit tests
├── test_theme_manager.py    # ThemeManager unit tests
├── test_display_modes.py    # DisplayMode unit tests
└── test_gif_video.py        # GIF and Video animation tests
```

## Adding New Tests

### 1. Create test file
```python
# tests/test_new_component.py
import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import NewComponent

class TestNewComponent(unittest.TestCase):
    def test_something(self):
        component = NewComponent()
        self.assertTrue(component.works())

if __name__ == '__main__':
    unittest.main()
```

### 2. Run test
```bash
python3 -m unittest tests/test_new_component.py
```

### 3. Test will be automatically included in test suite
```bash
python3 tests/run_tests.py
```

## Principles

- **Isolation**: Each test is independent
- **Clarity**: Test names describe what they test
- **Coverage**: Test both success and failure paths
- **Fast**: All tests run in < 1 second
- **No Side Effects**: Tests clean up after themselves

## Future Tests

- [ ] ButtonFactory unit tests
- [ ] BasePanel unit tests (requires tkinter mocking)
- [ ] Full GUI integration tests
- [ ] Device communication tests (mock LCD device)
- [ ] End-to-end workflow tests
