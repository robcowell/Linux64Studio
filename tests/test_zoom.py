import pytest

from l64s import zoom
from l64s.settings import Settings


def test_a_collapsed_panel_comes_back_at_its_size():
    assert zoom.restored(300, 1280) == 300


def test_a_collapsed_panel_leaves_the_editor_room_if_the_window_shrank():
    assert zoom.restored(700, 800) == 640


def test_the_panels_are_open_by_default():
    settings = Settings()
    assert settings.show_file_tree and settings.show_project_info and settings.show_bottom_panel


def test_larger_and_smaller_walk_the_steps():
    assert zoom.larger(100) == 110
    assert zoom.smaller(100) == 90


def test_the_ends_stay_put():
    assert zoom.larger(zoom.STEPS[-1]) == zoom.STEPS[-1]
    assert zoom.smaller(zoom.STEPS[0]) == zoom.STEPS[0]


def test_every_step_is_reachable_in_both_directions():
    up = [zoom.STEPS[0]]
    while up[-1] != zoom.STEPS[-1]:
        up.append(zoom.larger(up[-1]))
    assert tuple(up) == zoom.STEPS
    down = [zoom.STEPS[-1]]
    while down[-1] != zoom.STEPS[0]:
        down.append(zoom.smaller(down[-1]))
    assert tuple(reversed(down)) == zoom.STEPS


@pytest.mark.parametrize("stored, used", [(150, 150), (130, 125), (10, 75), (999, 300), (112.5, 110),
                                          ("big", 100), (None, 100), (True, 100)])
def test_valid_makes_a_step_of_what_the_settings_hold(stored, used):
    assert zoom.valid(stored) == used


def test_panel_grows_with_the_text():
    assert zoom.fitted(240, 3000, 1.5) == 360


def test_panel_stops_growing_at_its_share_of_the_space():
    assert zoom.fitted(240, 1000, 2.0) == 400


def test_panel_already_over_its_share_stays_as_it_is():
    assert zoom.fitted(600, 1000, 2.0) == 600


def test_panel_returns_to_its_size_after_reaching_its_limit():
    p = zoom.Panel()
    size = p.resized(240, 1000, 1.0, 2.0)
    assert size == 400
    size = p.resized(size, 1000, 2.0, 3.0)
    assert size == 400
    assert p.resized(size, 1000, 3.0, 1.0) == 240


def test_dragged_panel_keeps_its_new_size():
    p = zoom.Panel()
    p.resized(240, 3000, 1.0, 2.0)                  # 480, then dragged to 600
    assert p.resized(600, 3000, 2.0, 1.0) == 300


def test_text_zoom_is_kept_in_the_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    s = Settings.load()
    assert s.text_zoom == 100
    s.text_zoom = 150
    s.save()
    assert Settings.load().text_zoom == 150
