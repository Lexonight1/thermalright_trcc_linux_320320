"""
Tests for EventBus - Event system component.
"""

import unittest
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import EventBus


class TestEventBus(unittest.TestCase):
    """Test EventBus publish-subscribe functionality."""

    def setUp(self):
        """Create fresh EventBus for each test."""
        self.event_bus = EventBus()
        self.callback_data = []

    def test_subscribe_and_publish(self):
        """Test basic subscribe and publish."""
        def callback(data):
            self.callback_data.append(data)

        self.event_bus.subscribe('test_event', callback)
        self.event_bus.publish('test_event', 'test_data')

        self.assertEqual(len(self.callback_data), 1)
        self.assertEqual(self.callback_data[0], 'test_data')

    def test_multiple_subscribers(self):
        """Test multiple subscribers to same event."""
        results = []

        def callback1(data):
            results.append(f'cb1:{data}')

        def callback2(data):
            results.append(f'cb2:{data}')

        self.event_bus.subscribe('test_event', callback1)
        self.event_bus.subscribe('test_event', callback2)
        self.event_bus.publish('test_event', 'data')

        self.assertEqual(len(results), 2)
        self.assertIn('cb1:data', results)
        self.assertIn('cb2:data', results)

    def test_unsubscribe(self):
        """Test unsubscribing from events."""
        def callback(data):
            self.callback_data.append(data)

        self.event_bus.subscribe('test_event', callback)
        self.event_bus.publish('test_event', 'data1')

        self.event_bus.unsubscribe('test_event', callback)
        self.event_bus.publish('test_event', 'data2')

        # Should only receive first publish
        self.assertEqual(len(self.callback_data), 1)
        self.assertEqual(self.callback_data[0], 'data1')

    def test_publish_no_subscribers(self):
        """Test publishing event with no subscribers."""
        # Should not raise exception
        self.event_bus.publish('nonexistent_event', 'data')

    def test_callback_exception_handling(self):
        """Test that exception in callback doesn't break other callbacks."""
        results = []

        def bad_callback(data):
            raise ValueError("Test error")

        def good_callback(data):
            results.append(data)

        self.event_bus.subscribe('test_event', bad_callback)
        self.event_bus.subscribe('test_event', good_callback)

        # Should not raise, good_callback should still execute
        self.event_bus.publish('test_event', 'data')

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0], 'data')

    def test_clear_event(self):
        """Test clearing all subscribers for an event."""
        def callback(data):
            self.callback_data.append(data)

        self.event_bus.subscribe('test_event', callback)
        self.event_bus.clear_event('test_event')
        self.event_bus.publish('test_event', 'data')

        # Should not receive any data
        self.assertEqual(len(self.callback_data), 0)

    def test_clear_all(self):
        """Test clearing all subscribers for all events."""
        def callback(data):
            self.callback_data.append(data)

        self.event_bus.subscribe('event1', callback)
        self.event_bus.subscribe('event2', callback)

        self.event_bus.clear_all()

        self.event_bus.publish('event1', 'data1')
        self.event_bus.publish('event2', 'data2')

        # Should not receive any data
        self.assertEqual(len(self.callback_data), 0)

    def test_get_subscriber_count(self):
        """Test getting subscriber count."""
        def callback1(data): pass
        def callback2(data): pass

        self.assertEqual(self.event_bus.get_subscriber_count('test_event'), 0)

        self.event_bus.subscribe('test_event', callback1)
        self.assertEqual(self.event_bus.get_subscriber_count('test_event'), 1)

        self.event_bus.subscribe('test_event', callback2)
        self.assertEqual(self.event_bus.get_subscriber_count('test_event'), 2)

    def test_duplicate_subscription(self):
        """Test that duplicate subscriptions are ignored."""
        def callback(data):
            self.callback_data.append(data)

        self.event_bus.subscribe('test_event', callback)
        self.event_bus.subscribe('test_event', callback)  # Duplicate

        self.event_bus.publish('test_event', 'data')

        # Should only be called once
        self.assertEqual(len(self.callback_data), 1)


if __name__ == '__main__':
    unittest.main()
