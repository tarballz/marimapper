import io
from contextlib import redirect_stdout

from marimapper import sfm_process
from marimapper.sfm_process import print_without_hiding_scan_message


def test_status_message_does_not_redraw_scan_prompt():
    """Async SFM status messages must not re-print the 'Start scan?' prompt.
    Re-printing it makes the terminal appear to ask twice, and any extra
    'y' the user types is buffered in stdin and triggers a ghost scan
    after the real one finishes."""

    sfm_process._last_printed_message = ""
    buf = io.StringIO()
    with redirect_stdout(buf):
        print_without_hiding_scan_message("Reconstructed 100/200 in 1s")

    out = buf.getvalue()
    assert "Reconstructed 100/200 in 1s" in out
    assert "Start scan?" not in out


def test_consecutive_duplicate_messages_are_suppressed():
    """Five callsites emit the recovery summary at different stages and
    often produce identical text in a row — the user sees it spam. Only
    the first should print until the content changes."""

    sfm_process._last_printed_message = ""
    buf = io.StringIO()
    with redirect_stdout(buf):
        print_without_hiding_scan_message("Recovered 1168/10000 LEDs: ...")
        print_without_hiding_scan_message("Recovered 1168/10000 LEDs: ...")
        print_without_hiding_scan_message("Recovered 1168/10000 LEDs: ...")
        print_without_hiding_scan_message("Recovered 1170/10000 LEDs: ...")
        print_without_hiding_scan_message("Recovered 1170/10000 LEDs: ...")

    out = buf.getvalue()
    assert out.count("Recovered 1168/10000 LEDs: ...") == 1
    assert out.count("Recovered 1170/10000 LEDs: ...") == 1
