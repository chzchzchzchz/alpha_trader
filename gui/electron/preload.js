const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('electronAPI', {
  getStatus: () => ipcRenderer.invoke('get-status'),
  getPortfolio: () => ipcRenderer.invoke('get-portfolio'),
  placeTrade: (ticker, side) => ipcRenderer.invoke('trade', { ticker, side }),
});
