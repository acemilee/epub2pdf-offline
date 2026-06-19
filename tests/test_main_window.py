from epub2pdf.ui import main_window


def test_gui_allows_only_one_conversion_at_a_time_by_default():
    assert main_window.MAX_CONCURRENT_CONVERSIONS == 1
