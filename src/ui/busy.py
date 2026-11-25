"""Shared "working..." feedback for blocking operations: status-bar message plus busy cursor."""
from contextlib import contextmanager, ExitStack
from PyQt6.QtCore import Qt, QEventLoop, QEvent, QObject
from PyQt6.QtWidgets import QApplication, QLabel

OVERLAY_STYLE = ('QLabel{background:rgba(255,255,255,0.82);color:#15324f;font-size:13pt;font-weight:600;'
                 'border:1px solid #d7e0ea;border-radius:6px;}')


def status_bar(widget):
    """Status bar of the window containing a widget.

    Parameters
    ----------
    widget : QWidget or None
        Any widget in the main window.

    Returns
    -------
    QStatusBar or None
        The status bar, or None if the widget's window has none.
    """
    window = widget.window() if widget is not None else None
    return window.statusBar() if window is not None and hasattr(window, 'statusBar') else None


def show_status(widget, message, timeout=0):
    """Show a message in the status bar of the window containing a widget.

    Parameters
    ----------
    widget : QWidget or None
        Any widget in the main window.
    message : str
        Text to show.
    timeout : int, optional
        Milliseconds before the message disappears; 0 keeps it until replaced.
    """
    bar = status_bar(widget)
    if bar is not None:
        bar.showMessage(message, timeout)


@contextmanager
def busy(widget, message):
    """Show `message` in the status bar and a wait cursor while the block runs.

    The work runs on the GUI thread, so the window repaints once before it starts;
    clicks made meanwhile are held until the work finishes.

    Parameters
    ----------
    widget : QWidget
        Any widget in the main window.
    message : str
        What is being done, e.g. 'Applying filter result...'.

    Yields
    ------
    None
        Control returns to the with-block.
    """
    show_status(widget, message)
    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
    try:
        yield
    finally:
        QApplication.restoreOverrideCursor()


class LoadingOverlay(QLabel):
    """Semi-transparent message drawn over a plot or web map while it is being drawn or loaded.

    The overlay follows the size of the widget it covers. Calls can be nested; it is hidden when the outermost
    one finishes.

    Parameters
    ----------
    target : QWidget
        Plot canvas, web view or other widget to cover.
    """

    def __init__(self, target):
        """Create the hidden overlay on top of the target widget (see the class description)."""
        super().__init__(target)
        self.target = target
        self.depth = 0
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWordWrap(True)
        self.setStyleSheet(OVERLAY_STYLE)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.hide()
        target.installEventFilter(self)

    def eventFilter(self, obj, event):
        """Keep covering the target when it is resized.

        Parameters
        ----------
        obj : QObject
            The covered widget.
        event : QEvent
            The event.

        Returns
        -------
        bool
            Always False, so the event is handled normally.
        """
        if obj is self.target and event.type() == QEvent.Type.Resize:
            self.setGeometry(self.target.rect())
        return False

    def show_message(self, message):
        """Show the overlay with a message and paint it at once (before blocking work starts).

        Parameters
        ----------
        message : str
            Text, e.g. 'Drawing cleaning map...'.
        """
        self.setText(message)
        self.setGeometry(self.target.rect())
        self.raise_()
        self.show()
        self.repaint()


def overlay_for(widget):
    """The loading overlay of a widget, created on first use.

    Parameters
    ----------
    widget : QWidget
        Plot canvas, web view or other widget.

    Returns
    -------
    LoadingOverlay
        The widget's overlay.
    """
    overlay = getattr(widget, '_loading_overlay', None)
    if overlay is None:
        overlay = LoadingOverlay(widget)
        widget._loading_overlay = overlay
    return overlay


@contextmanager
def loading(widgets, message):
    """Show 'message' over the given plots (and in the status bar, with a wait cursor) while the block runs.

    Only widgets on screen get an overlay. Matplotlib canvases are drawn before the overlay is removed, so the
    message stays until the plot is really there.

    Parameters
    ----------
    widgets : QWidget or list of QWidget
        Canvases or other widgets that are being redrawn.
    message : str
        What is being drawn, e.g. 'Drawing cleaning map...'.

    Yields
    ------
    None
        Control returns to the with-block.
    """
    widgets = [w for w in (widgets if isinstance(widgets, (list, tuple)) else [widgets]) if w is not None]
    shown = [w for w in widgets if w.isVisible()]
    overlays = []
    for widget in shown:
        overlay = overlay_for(widget)
        overlay.depth += 1
        overlay.show_message(message)
        overlays.append(overlay)
    with ExitStack() as stack:
        if shown:
            stack.enter_context(busy(shown[0], message))
        try:
            yield
        finally:
            for overlay in overlays:
                overlay.depth -= 1
                if overlay.depth == 0:
                    draw = getattr(overlay.target, 'draw', None)
                    if callable(draw) and hasattr(overlay.target, 'figure'):
                        try:
                            draw()
                        except Exception:
                            pass
                    overlay.hide()
            bar = status_bar(shown[0]) if shown else None
            if bar is not None and bar.currentMessage() == message:
                bar.clearMessage()


class _WebLoadWatcher(QObject):
    """Shows a web view's overlay from loadStarted until loadFinished (web maps load in the background)."""

    def __init__(self, view, message):
        """Connect to the web view's load signals.

        Parameters
        ----------
        view : QWebEngineView
            Web map view.
        message : str
            Text shown while a page loads.
        """
        super().__init__(view)
        self.view, self.message = view, message
        view.loadStarted.connect(self.started)
        view.loadFinished.connect(self.finished)

    def started(self):
        """Page started loading: show the message."""
        if self.view.isVisible():
            overlay_for(self.view).show_message(self.message)
            show_status(self.view, self.message)

    def finished(self, ok):
        """Page loaded (or failed): remove the message.

        Parameters
        ----------
        ok : bool
            Whether the page loaded.
        """
        overlay = overlay_for(self.view)
        if overlay.isVisible():
            overlay.hide()
            show_status(self.view, 'Map loaded.' if ok else 'The map could not be loaded.', 4000)


def watch_web_view(view, message='Loading map...'):
    """Show a loading message over a web view whenever it loads a page.

    Parameters
    ----------
    view : QWebEngineView
        Web map view.
    message : str, optional
        Text shown while the page loads.

    Returns
    -------
    QObject
        The watcher (kept alive by the view).
    """
    return _WebLoadWatcher(view, message)
