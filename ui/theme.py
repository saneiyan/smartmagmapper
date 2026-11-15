from pathlib import Path
import numpy as np
import matplotlib
from matplotlib import get_data_path, colormaps
from matplotlib.colors import to_hex
from PyQt6.QtGui import QIcon,QImage,QPixmap,QPalette
from PyQt6.QtCore import Qt,QSize
from PyQt6.QtWidgets import QToolButton,QWidget,QHBoxLayout,QComboBox,QApplication

# Colour scales offered for spatial maps: (menu label, matplotlib colormap name).
COLOR_SCALES=[('Viridis','viridis'),('Cividis','cividis'),('Plasma','plasma'),('Magma','magma'),
              ('Inferno','inferno'),('Turbo','turbo'),('Spectral','Spectral_r'),('Red\u2013Yellow\u2013Blue','RdYlBu_r'),
              ('Cool\u2013Warm','coolwarm'),('Blues','Blues'),('Greyscale','gray')]


def color_scale_combo(default='viridis'):
    """Dropdown of colour scales, each shown with a small gradient preview; currentData() is the colormap name."""
    combo=QComboBox();combo.setIconSize(QSize(64,12))
    for label,name in COLOR_SCALES:
        rgb=np.ascontiguousarray(np.repeat((colormaps[name](np.linspace(0,1,64))[None,:,:3]*255).astype(np.uint8),12,axis=0))
        image=QImage(rgb.data,64,12,64*3,QImage.Format.Format_RGB888).copy()
        combo.addItem(QIcon(QPixmap.fromImage(image)),label,name)
    combo.setCurrentIndex(max(0,combo.findData(default)))
    combo.setToolTip('Colour scale (gradient) used for the map colours and colour bar.')
    return combo


def color_list(name,count=16):
    """Hex colours sampled along a colormap, for web-map (folium/branca) colour scales."""
    return [to_hex(colormaps[name](value)) for value in np.linspace(0,1,count)]

# Light, compact buttons for panel toggles and view arrows (overrides the app's navy QToolButton style).
SMALL_BUTTON_STYLE=('QToolButton{background:#f1f5f9;color:#172b4d;padding:4px 8px;border:1px solid #d7e0ea;border-radius:4px;}'
                    'QToolButton:hover{background:#e0ebf4;}'
                    'QToolButton:disabled{color:#96a3b0;background:#f8fafc;border:1px solid #e8edf3;}')


def small_tool_button(text='',arrow=None,tooltip=''):
    button=QToolButton();button.setStyleSheet(SMALL_BUTTON_STYLE)
    button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    if arrow is not None:button.setArrowType(arrow)
    button.setText(text);button.setToolTip(tooltip)
    return button


class TabArrows(QWidget): # Not needed.
    """Small ◀ ▶ buttons in a tab widget's top-right corner that step through its sub-tabs.

    Hidden or disabled tabs are skipped, and the arrows never leave this tab widget.
    Call refresh() after showing or hiding tabs (Qt has no signal for tab visibility).
    """
    def __init__(self,tabs):
        super().__init__()
        self.tabs=tabs
        layout=QHBoxLayout(self);layout.setContentsMargins(0,0,4,0);layout.setSpacing(4)
        self.previous=small_tool_button(arrow=Qt.ArrowType.LeftArrow)
        self.next=small_tool_button(arrow=Qt.ArrowType.RightArrow)
        for button,delta in ((self.previous,-1),(self.next,1)):
            button.clicked.connect(lambda _=False,delta=delta:self.step(delta));layout.addWidget(button)
        tabs.setCornerWidget(self,Qt.Corner.TopRightCorner)
        tabs.currentChanged.connect(self.refresh)
        self.refresh()

    def neighbour(self,delta):
        index=self.tabs.currentIndex()+delta
        while 0<=index<self.tabs.count():
            if self.tabs.isTabVisible(index) and self.tabs.isTabEnabled(index):return index
            index+=delta
        return None

    def step(self,delta):
        index=self.neighbour(delta)
        if index is not None:self.tabs.setCurrentIndex(index)

    def refresh(self,*_):
        for button,delta,word,edge in ((self.previous,-1,'Previous','first'),(self.next,1,'Next','last')):
            index=self.neighbour(delta)
            button.setEnabled(index is not None)
            button.setToolTip(f'{word} view: {self.tabs.tabText(index)}' if index is not None else f'This is the {edge} view.')


def panel_toggle(panel,open_text,closed_text='Settings',name='settings',on_change=None):
    """Small collapse button for a side panel: '◀ open_text' while shown, '▶ closed_text' while hidden.

    Place it directly above the panel; it stays visible while the panel is collapsed.
    on_change(visible) runs after each toggle (e.g. to resize a splitter).
    """
    # Plain QToolButton with NO stylesheet: it inherits the app style (Fusion + the
    # main window's stylesheet) like every other button. small_tool_button() would
    # force SMALL_BUTTON_STYLE, which clashes with the app style.
    button=QToolButton();button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    button.setCheckable(True);button.setChecked(True)
    def update(visible):
        panel.setVisible(visible)
        button.setArrowType(Qt.ArrowType.LeftArrow if visible else Qt.ArrowType.RightArrow)
        button.setText(open_text if visible else closed_text)
        button.setToolTip(f'Collapse the {name} panel to give the plots more room.' if visible else f'Show the {name} panel.')
        if on_change is not None:on_change(visible)
    button.toggled.connect(update);update(True)
    return button


def is_dark_theme():
    """True when the OS/Qt colour scheme is dark (Qt 6.5+), else palette-luminance fallback."""
    app = QApplication.instance()
    if app is None:
        return False
    hints = app.styleHints()
    if hasattr(hints, 'colorScheme'):
        return hints.colorScheme() == Qt.ColorScheme.Dark
    c = app.palette().color(QPalette.ColorRole.Window)
    return (0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()) < 128


# (figure bg, axes bg, main text, tick text, spine, grid, legend edge) per scheme.
_FIGURE_THEMES = {
    False: ('white', 'white', '#172b4d', '#334155', '#94a3b8', '#64748b', '#cbd5e1'),
    True: ('#1e293b', '#1e293b', '#e2e8f0', '#cbd5e1', '#64748b', '#94a3b8', '#475569'),
}


def _rc_dict(dark):
    fig_bg, axes_bg, text, tick, spine, grid, _ = _FIGURE_THEMES[dark]
    return {
        'figure.facecolor': fig_bg, 'axes.facecolor': axes_bg,
        'savefig.facecolor': fig_bg,
        'axes.edgecolor': spine, 'axes.labelcolor': text,
        'text.color': text, 'xtick.color': tick, 'ytick.color': tick,
        'grid.color': grid,
    }


def apply_matplotlib_theme():
    """Set matplotlib rcParams from the current OS scheme. Call once at startup,
    right after QApplication is created and before any Figure exists -- every
    figure created afterwards (all tabs, no per-figure edits) inherits it."""
    matplotlib.rcParams.update(_rc_dict(is_dark_theme()))


def plot_palette():
    """Current scheme's plot colours as a dict, for plotting code that sets
    colours explicitly (bg, text, tick, spine, grid, legend_edge)."""
    fig_bg, axes_bg, text, tick, spine, grid, legend_edge = _FIGURE_THEMES[is_dark_theme()]
    return {'figure_bg': fig_bg, 'bg': axes_bg, 'text': text, 'tick': tick,
            'spine': spine, 'grid': grid, 'legend_edge': legend_edge}


def _style_figure(figure, dark):
    fig_bg, axes_bg, text, tick, spine, grid, legend_edge = _FIGURE_THEMES[dark]
    figure.set_facecolor(fig_bg)
    for ax in figure.axes:
        ax.set_facecolor(axes_bg)
        ax.tick_params(colors=tick, which='both')
        ax.xaxis.label.set_color(text)
        ax.yaxis.label.set_color(text)
        ax.title.set_color(text)
        ax.xaxis.get_offset_text().set_color(tick)
        ax.yaxis.get_offset_text().set_color(tick)
        for t in ax.texts: t.set_color(text)
        for s in ax.spines.values(): s.set_color(spine)
        ax.grid(color=grid, alpha=.15)
        legend = ax.get_legend()
        if legend:
            legend.get_frame().set_facecolor(fig_bg)
            legend.get_frame().set_edgecolor(legend_edge)
            for t in legend.get_texts(): t.set_color(text)


def light_figure(figure):
    """Restyle a figure for the current OS scheme (name kept: existing callers unchanged)."""
    _style_figure(figure, is_dark_theme())


import contextlib


@contextlib.contextmanager
def print_theme():
    """Force the light (print) theme inside the block -- wrap the CREATION of
    export figures in this so they come out print-friendly in either OS scheme."""
    with matplotlib.rc_context(_rc_dict(False)):
        yield


def save_print_friendly(figure, path, **kwargs):
    """Save an on-screen figure print-friendly: temporarily restyle it light,
    swap data drawn in the dark scheme's text colour to the light one, save,
    then restore the on-screen (OS scheme) styling."""
    kwargs.setdefault('facecolor', 'white')
    dark_text = _FIGURE_THEMES[True][2]
    light_text = _FIGURE_THEMES[False][2]
    swapped = []
    if is_dark_theme():
        from matplotlib.colors import to_rgba
        for ax in figure.axes:
            for line in ax.get_lines():
                if line.get_color() and to_rgba(line.get_color()) == to_rgba(dark_text):
                    line.set_color(light_text); swapped.append(line)
    _style_figure(figure, False)
    try:
        figure.savefig(path, **kwargs)
    finally:
        _style_figure(figure, is_dark_theme())
        for line in swapped: line.set_color(dark_text)


def compact_toolbar(toolbar):
    """Native, labelled navigation with clear active states and full click targets."""
    toolbar.setMinimumHeight(40)
    toolbar.setMaximumHeight(48)
    toolbar.setIconSize(QSize(18,18))
    toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    if is_dark_theme():
        toolbar.setStyleSheet("""
          QToolBar {background:#1e293b;padding:2px;spacing:3px;border-bottom:1px solid #334155;}
          QToolButton {background:#263449;color:#e2e8f0;padding:4px 7px;border:1px solid transparent;border-radius:4px;}
          QToolButton:hover {background:#334155;}
          QToolButton:pressed,QToolButton:checked {background:#3b5a78;border:1px solid #587c9d;color:#ffffff;}
          QToolButton:disabled {color:#64748b;background:#1e293b;}
          QLabel {color:#cbd5e1;}
        """)
    else:
        toolbar.setStyleSheet("""
          QToolBar {background:#ffffff;padding:2px;spacing:3px;border-bottom:1px solid #d7e0ea;}
          QToolButton {background:#f1f5f9;color:#172b4d;padding:4px 7px;border:1px solid transparent;border-radius:4px;}
          QToolButton:hover {background:#e0ebf4;}
          QToolButton:pressed,QToolButton:checked {background:#adc8df;border:1px solid #587c9d;color:#102b46;}
          QToolButton:disabled {color:#96a3b0;background:#f8fafc;}
          QLabel {color:#172b4d;}
        """)
    for callback in ['configure_subplots','edit_parameters']:
        if callback in toolbar._actions:toolbar.removeAction(toolbar._actions[callback])
    for text,tip,filename,callback in toolbar.toolitems:
        if filename and callback in toolbar._actions:
            path=Path(get_data_path())/'images'/(filename+'.svg')
            if path.exists():toolbar._actions[callback].setIcon(QIcon(str(path)))
    if is_dark_theme():
        # matplotlib's SVG toolbar glyphs are drawn dark for light backgrounds;
        # invert them (alpha preserved) so they read on the dark toolbar.
        for action in toolbar._actions.values():
            icon = action.icon()
            pixmap = icon.pixmap(QSize(36, 36))
            if not pixmap.isNull():
                image = pixmap.toImage()
                image.invertPixels(QImage.InvertMode.InvertRgb)
                action.setIcon(QIcon(QPixmap.fromImage(image)))
    descriptions = {
        'home': ('Reset View', 'Restore the original axis limits for this plot.'),
        'back': ('Back', 'Return to the previous plot view after zooming or panning. Disabled when there is no earlier view.'),
        'forward': ('Forward', 'Return to a later plot view after using Back. Disabled when there is no later view.'),
    }
    for key, (label, description) in descriptions.items():
        if key in toolbar._actions:
            action = toolbar._actions[key]
            action.setText(label)
            action.setToolTip(description)
            action.setStatusTip(description)
