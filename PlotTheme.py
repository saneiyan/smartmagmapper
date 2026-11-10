from pathlib import Path
from matplotlib import get_data_path
from PyQt6.QtGui import QIcon
from PyQt6.QtCore import Qt,QSize


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

