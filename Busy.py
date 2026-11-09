"""Shared "working..." feedback for blocking operations: status-bar message plus busy cursor."""
from contextlib import contextmanager
from PyQt6.QtCore import Qt, QEventLoop
from PyQt6.QtWidgets import QApplication


def status_bar(widget):
    window = widget.window() if widget is not None else None
    return window.statusBar() if window is not None and hasattr(window, 'statusBar') else None


def show_status(widget, message, timeout=0):
    bar = status_bar(widget)
    if bar is not None:
        bar.showMessage(message, timeout)


@contextmanager
def busy(widget, message):
    """Show `message` in the status bar and a wait cursor while the block runs.

    The work runs on the GUI thread, so the window repaints once before it starts;
    clicks made meanwhile are held until the work finishes.
    """
    show_status(widget, message)
    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
    try:
        yield
    finally:
        QApplication.restoreOverrideCursor()
