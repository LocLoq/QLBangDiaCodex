import json
from types import SimpleNamespace

from matplotlib.figure import Figure

from normastore.config import Settings
from normastore.ui.theme import AppearanceMixin, _load_preferences, _preferences_path, theme_palette
from normastore.ui.tooltips import tooltip_position
from normastore.ui.widgets import CommonWidgetsMixin


def test_tooltip_position_flips_and_clamps_at_virtual_screen_edges():
    assert tooltip_position(990, 790, 180, 120, 0, 0, 1000, 800) == (794, 654)
    assert tooltip_position(-990, -790, 180, 120, -1000, -800, 1000, 800) == (-974, -774)


def test_dark_palette_is_readable_and_uses_slate_surface():
    palette = theme_palette(True)

    assert palette.background == "#2B3E50"
    assert palette.surface == "#32465A"
    assert palette.foreground == "#F8FAFC"
    assert palette.muted == "#C4CED8"


def test_darkly_preference_migrates_to_superhero(tmp_path, monkeypatch):
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    settings = Settings(cache_dir=tmp_path)
    path = _preferences_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"theme": "darkly", "font_scale": "Lớn"}), encoding="utf-8")

    assert _load_preferences(settings) == {"theme": "superhero", "font_scale": "Lớn"}


def test_invalid_preferences_fall_back_to_light_medium(tmp_path, monkeypatch):
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    settings = Settings(cache_dir=tmp_path)
    path = _preferences_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not-json", encoding="utf-8")

    assert _load_preferences(settings) == {"theme": "flatly", "font_scale": "Vừa"}


def test_figure_restyles_after_axis_clear():
    figure = Figure()
    axis = figure.add_subplot(111)
    app = SimpleNamespace(_palette=theme_palette(True))

    AppearanceMixin._style_figure(app, figure)
    axis.clear()
    AppearanceMixin._style_figure(app, figure)

    assert figure.get_facecolor()[:3] == (43 / 255, 62 / 255, 80 / 255)
    assert axis.get_facecolor()[:3] == (43 / 255, 62 / 255, 80 / 255)
    assert axis.title.get_color() == "#F8FAFC"


def test_treeview_factory_centers_tree_and_value_columns(monkeypatch):
    calls = []

    class FakeTree:
        def __init__(self, parent, **kwargs):
            self.kwargs = kwargs

        def __getitem__(self, key):
            assert key == "columns"
            return self.kwargs["columns"]

        def column(self, column, **kwargs):
            calls.append(("column", column, kwargs))

        def heading(self, column, **kwargs):
            calls.append(("heading", column, kwargs))

    monkeypatch.setattr("normastore.ui.widgets.ttk.Treeview", FakeTree)

    tree = CommonWidgetsMixin._create_treeview(
        object(),
        object(),
        columns=("first", "second"),
        show="headings",
        height=4,
        selectmode="extended",
    )

    assert tree.kwargs == {
        "columns": ("first", "second"),
        "show": "headings",
        "height": 4,
        "selectmode": "extended",
    }
    assert calls == [
        ("column", "#0", {"anchor": "center"}),
        ("heading", "#0", {"anchor": "center"}),
        ("column", "first", {"anchor": "center"}),
        ("heading", "first", {"anchor": "center"}),
        ("column", "second", {"anchor": "center"}),
        ("heading", "second", {"anchor": "center"}),
    ]
