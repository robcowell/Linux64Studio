from l64s.emu.vice import joystick_args


def test_joystick_args():
    assert joystick_args("none", "none") == []
    assert joystick_args("none", "keypad") == ["-joydev2", "1"]
    assert joystick_args("joy1", "keyset1") == ["-joydev1", "4", "-joydev2", "2"]
    assert joystick_args("none", "keypad", ["-joydev2", "3"]) == []          # typed options win
    assert joystick_args("nonsense", "none") == []
