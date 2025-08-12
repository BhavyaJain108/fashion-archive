const { contextBridge, ipcRenderer } = require('electron');

// Expose protected methods that allow the renderer process to use
// the ipcRenderer without exposing the entire object
contextBridge.exposeInMainWorld('electronAPI', {
  // Python backend communication
  callPython: (method, args) => ipcRenderer.invoke('python-call', { method, args }),
  
  // File system operations
  openFile: (path) => ipcRenderer.invoke('open-file', path),
  
  // Window operations
  minimize: () => ipcRenderer.invoke('minimize-window'),
  maximize: () => ipcRenderer.invoke('maximize-window'),
  close: () => ipcRenderer.invoke('close-window'),
  
  // Listen for backend events
  onBackendEvent: (callback) => ipcRenderer.on('backend-event', callback),
  
  // Remove listeners
  removeAllListeners: (channel) => ipcRenderer.removeAllListeners(channel)
});