import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import sys, os

class PlotData:
    def __init__(self, df):
        self.df = df
        self.fig = None

    def plot(self, color=None, size=None, x=None, val=None, xmin=None, xmax=None, ymin=None, ymax=None, ax=None, title=None):
        if val is None:
            val = self.df['BT']
            data = val.values
        else:
            data = val.values
        if ax is None:
            self.fig, ax = plt.subplots()
        else:
            self.fig = ax.figure
        if color is None:
            color = 'hotpink'
        if x is None:
            x = self.df['Mag_Time (s)']
        # if xmin is None:
        #     xmin = 0
        #if xmax is None:
        #    xmax = x.max()
        if ymin is None:
            ymin = val.min()
        if ymax is None:
            ymax = val.max()

        ax.scatter(x, data, color=color, edgecolor='black')
        ax.set_xlim(xmin, xmax)
        ax.set_ylim(ymin, ymax)
        if title is None:
            title = 'Total Magnetic Field v Time'
        ax.set_title(title)
        ax.set_ylabel(f'{val.name}')
        ax.set_xlabel('Time (s)')

    def save_plot(self, filename=None):
        if filename is None:
            filename = 'magneticdata.png'
        # if not os.path.exists(figures_dir):
        #            os.makedirs(figures_dir)
        # plt.savefig(os.path.join(figures_dir, filename))
        self.fig.savefig(filename)
