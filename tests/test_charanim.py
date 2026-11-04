"""Character animation preview."""
from l64s.gfx.charanim import PING_PONG, describe_speed, frame_chars, frame_starts, order


def test_frames():
    assert frame_starts(10, 13) == [10, 11, 12, 13]
    assert frame_starts(13, 10) == [13, 12, 11, 10]
    assert frame_starts(64, 79, 4) == [64, 68, 72, 76]           # 2x2 frames: 4 characters a frame
    assert frame_starts(252, 255, 4) == [252]
    assert frame_starts(254, 255, 4) == []                        # runs past 255
    assert frame_starts(5, 5) == [5]


def test_order():
    assert order(4) == [0, 1, 2, 3]
    assert order(4, PING_PONG) == [0, 1, 2, 3, 2, 1]
    assert order(2, PING_PONG) == [0, 1] and order(1, PING_PONG) == [0] and order(0) == []


def test_frame_chars_and_speed():
    assert frame_chars(64, 2, 2) == [[64, 65], [66, 67]]
    assert frame_chars(7) == [[7]]
    assert describe_speed(5) == "every 5 frames (10 a second)" and describe_speed(1).startswith("every 1 frame (")
