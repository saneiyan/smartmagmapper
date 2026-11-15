from pathlib import Path
import numpy as np
from matplotlib import get_data_path, colormaps
from matplotlib.colors import to_hex
from PyQt6.QtGui import QIcon,QImage,QPixmap
from PyQt6.QtCore import Qt,QSize
from PyQt6.QtWidgets import QToolButton,QWidget,QHBoxLayout,QComboBox

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
    button=small_tool_button();button.setCheckable(True);button.setChecked(True)
    def update(visible):
        panel.setVisible(visible)
        button.setArrowType(Qt.ArrowType.LeftArrow if visible else Qt.ArrowType.RightArrow)
        button.setText(open_text if visible else closed_text)
        button.setToolTip(f'Collapse the {name} panel to give the plots more room.' if visible else f'Show the {name} panel.')
        if on_change is not None:on_change(visible)
    button.toggled.connect(update);update(True)
    return button


def light_figure(figure):
    figure.set_facecolor('white')
    for ax in figure.axes:
        ax.set_facecolor('white')
        ax.tick_params(colors='#334155',which='both')
        ax.xaxis.label.set_color('#172b4d')
        ax.yaxis.label.set_color('#172b4d')
        ax.title.set_color('#172b4d')
        ax.xaxis.get_offset_text().set_color('#334155')
        ax.yaxis.get_offset_text().set_color('#334155')
        for text in ax.texts:text.set_color('#172b4d')
        for spine in ax.spines.values():spine.set_color('#94a3b8')
        ax.grid(color='#64748b',alpha=.15)
        legend=ax.get_legend()
        if legend:
            legend.get_frame().set_facecolor('white')
            legend.get_frame().set_edgecolor('#cbd5e1')
            for text in legend.get_texts():text.set_color('#172b4d')


def compact_toolbar(toolbar):
    """Native, labelled navigation with clear active states and full click targets."""
    toolbar.setMinimumHeight(40)
    toolbar.setMaximumHeight(48)
    toolbar.setIconSize(QSize(18,18))
    toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    toolbar.setStyleSheet("""
      QToolBar {background:#ffffff;padding:2px;spacing:3px;border-bottom:1px solid #d7e0ea;}
      QToolButton {background:#f1f5f9;color:#172b4d;padding:4px 7px;border:1px solid transparent;border-radius:4px;}
      QToolButton:hover {background:#e0ebf4;}
      QToolButton:pressed,QToolButton:checked {background:#adc8df;border:1px solid #587c9d;color:#102b46;}
      QToolButton:disabled {color:#96a3b0;background:#f8fafc;}
    """)
    for callback in ['configure_subplots','edit_parameters']:
        if callback in toolbar._actions:toolbar.removeAction(toolbar._actions[callback])
    for text,tip,filename,callback in toolbar.toolitems:
        if filename and callback in toolbar._actions:
            path=Path(get_data_path())/'images'/(filename+'.svg')
            if path.exists():toolbar._actions[callback].setIcon(QIcon(str(path)))
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
