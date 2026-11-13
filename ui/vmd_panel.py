"""Inspectable VMD reconstruction, mode traces, ratios, and selection reasons."""
import numpy as np
from ui.theme import light_figure
from processing import labels
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QWidget,QVBoxLayout,QLabel,QTabWidget,QScrollArea,
                            QTableWidget,QTableWidgetItem,QHeaderView)
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas

KEEP='#0f766e'
EXCLUDE='#b45309'


def exclusion_reason(row, selected):
    if int(row['mode']) in selected:
        return 'Keep — automatic recommendation'
    reasons=[]
    for key,label in [('trend_like','Trend-like'),('noise_like','Noise-like'),('extreme_high_rate','Extreme high rate')]:
        if bool(row.get(key,False)):
            reasons.append(label)
    return 'Exclude — '+(', '.join(reasons) if reasons else 'lower variance/rank or selection limit')


class VMDPanel(QWidget):
    selectionChanged=pyqtSignal(object)

    def __init__(self, editable=False, parent=None):
        super().__init__(parent)
        self.editable=editable
        self._updating=False
        self.payload=None
        layout=QVBoxLayout(self)
        self.summary=QLabel('Run VMD to inspect the reconstruction and all modes.')
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.tabs=QTabWidget();layout.addWidget(self.tabs)
        self.reconstruction=Figure(facecolor='white',figsize=(10,6),constrained_layout=True)
        self.reconstruction_canvas=FigureCanvas(self.reconstruction)
        self.tabs.addTab(self.reconstruction_canvas,'Original / Reconstructed / Removed')
        self.traces=Figure(facecolor='white',figsize=(12,14),constrained_layout=True)
        self.traces_canvas=FigureCanvas(self.traces)
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(self.traces_canvas)
        self.tabs.addTab(scroll,'Mode Traces + Variance Ratios')
        self.table=QTableWidget(0,7)
        self.table.setHorizontalHeaderLabels(['Keep','Mode','Variance ratio','Dominant rate','Flatness','Automatic recommendation','Current use'])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemChanged.connect(self._selection_changed)
        self.tabs.addTab(self.table,'Selection and Reasons')

    def clear(self, message='No decomposition for the current input.'):
        self.payload=None
        self._updating=True;self.table.setRowCount(0);self._updating=False
        self.summary.setText(message)
        for fig,canvas in [(self.reconstruction,self.reconstruction_canvas),(self.traces,self.traces_canvas)]:
            fig.clear();canvas.draw_idle()

    def set_data(self, axis, signal, modes, metrics, selected, axis_label='Time (s)', automatic=None):
        self.payload=(np.asarray(axis),np.asarray(signal),np.asarray(modes),metrics.copy(),list(selected),axis_label,
                      list(selected) if automatic is None else list(automatic))
        self._draw()

    def _draw(self):
        x,y,modes,metrics,selected,label,automatic=self.payload
        base=float(np.median(y))
        reconstructed=modes[np.array(selected,dtype=int)-1].sum(axis=0)+base if selected else np.full(len(y),base)
        removed=y-reconstructed
        self.summary.setText('Keep: '+(', '.join(map(str,selected)) or 'none')+' | Excluded: '+
            (', '.join(str(i) for i in range(1,len(modes)+1) if i not in selected) or 'none')+
            '. Exclusion affects reconstruction only; no mode is deleted. Variance ratio = mode variance / input variance (not a sum-to-one percentage).')
        self.reconstruction.clear()
        axes=self.reconstruction.subplots(3,1,sharex=True)
        axes[0].plot(x,y,color='#475569',lw=.8,label='Original input')
        axes[0].plot(x,reconstructed,color=KEEP,lw=.85,label='Selected reconstruction')
        axes[0].legend(fontsize=8);axes[0].set_title('Input and selected-mode reconstruction (median baseline restored)')
        axes[1].plot(x,reconstructed,color=KEEP,lw=.8);axes[1].set_title('Filtered reconstruction')
        axes[2].plot(x,removed,color=EXCLUDE,lw=.8);axes[2].set_title('Removed difference: input − reconstruction')
        for ax in axes:ax.grid(alpha=.2);ax.set_ylabel(labels.display_unit())
        axes[-1].set_xlabel(label);light_figure(self.reconstruction);self.reconstruction_canvas.draw_idle()
        self.traces.clear()
        self.traces.set_size_inches(12,max(7,len(modes)*1.5))
        self.traces_canvas.setMinimumHeight(max(650,len(modes)*125))
        gs=self.traces.add_gridspec(len(modes),2,width_ratios=[3.8,1.5])
        for index,row in metrics.reset_index(drop=True).iterrows():
            mode=int(row['mode']);keep=mode in selected;color=KEEP if keep else EXCLUDE
            ax=self.traces.add_subplot(gs[index,0])
            ax.plot(x,modes[mode-1],color=color,lw=.7)
            ax.set_title(f"Mode {mode} | ratio {row['variance_ratio']:.4f} | "+('KEEP' if keep else 'EXCLUDED'),fontsize=9,loc='left')
            ax.set_ylabel(labels.display_unit(),fontsize=8);ax.tick_params(labelsize=7);ax.grid(alpha=.15)
            if index==len(metrics)-1:ax.set_xlabel(label)
        bars=self.traces.add_subplot(gs[:,1])
        colors=[KEEP if int(m) in selected else EXCLUDE for m in metrics['mode']]
        bars.barh(metrics['mode'],metrics['variance_ratio'],color=colors)
        bars.invert_yaxis();bars.set_yticks(metrics['mode']);bars.set_ylabel('Mode')
        bars.set_xlabel('Variance ratio');bars.set_title('Green: keep\nAmber: excluded',fontsize=10)
        for _,row in metrics.iterrows():bars.text(row['variance_ratio'],row['mode'],f" {row['variance_ratio']:.3f}",va='center',fontsize=8)
        bars.margins(x=.25);light_figure(self.traces);self.traces_canvas.draw_idle()
        self._updating=True
        self.table.setRowCount(len(metrics))
        unit='Hz' if label.startswith('Time') else 'cycles/m'
        for i,row in metrics.reset_index(drop=True).iterrows():
            mode=int(row['mode']);keep=mode in selected
            check=QTableWidgetItem()
            check.setFlags(Qt.ItemFlag.ItemIsEnabled | (Qt.ItemFlag.ItemIsUserCheckable if self.editable else Qt.ItemFlag.NoItemFlags))
            check.setCheckState(Qt.CheckState.Checked if keep else Qt.CheckState.Unchecked)
            self.table.setItem(i,0,check)
            values=[str(mode),f"{row['variance_ratio']:.5f}",f"{row['dominant_rate_hz']:.5g} {unit}",
                    f"{row['spectral_flatness']:.4f}",exclusion_reason(row,automatic),'KEEP' if keep else 'EXCLUDED']
            for j,value in enumerate(values,1):
                item=QTableWidgetItem(value);item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                item.setForeground(QColor(KEEP if keep else EXCLUDE));self.table.setItem(i,j,item)
        self._updating=False

    def _selection_changed(self,item):
        if self._updating or item.column()!=0 or self.payload is None:return
        selected=[int(self.table.item(i,1).text()) for i in range(self.table.rowCount())
                  if self.table.item(i,0).checkState()==Qt.CheckState.Checked]
        if not selected:
            self._updating=True;item.setCheckState(Qt.CheckState.Checked);self._updating=False
            self.summary.setText('Keep at least one mode. No modes have been deleted.')
            return
        values=list(self.payload);values[4]=selected;self.payload=tuple(values)
        self._draw();self.selectionChanged.emit(selected)
