const { app, BrowserWindow, ipcMain } = require('electron');
const { spawn } = require('child_process');
const path = require('path');

// Simple isDev check
const isDev = process.env.NODE_ENV === 'development' || !app.isPackaged;

let mainWindow;
let pythonProcess;

function createWindow() {
  // Create the browser window with classic Mac styling
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    minWidth: 800,
    minHeight: 600,
    titleBarStyle: 'default', // Classic title bar
    backgroundColor: '#c0c0c0',
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      enableRemoteModule: false,
      preload: path.join(__dirname, 'preload.js')
    }
  });

  // Load the React app
  const startUrl = isDev 
    ? 'http://localhost:3000' 
    : `file://${path.join(__dirname, '../build/index.html')}`;
  
  mainWindow.loadURL(startUrl);

  // Open DevTools in development
  if (isDev) {
    mainWindow.webContents.openDevTools();
  }

  mainWindow.on('closed', () => {
    mainWindow = null;
    // Kill Python process when window closes
    if (pythonProcess) {
      pythonProcess.kill();
    }
  });
}

// Start Python backend server
function startPythonBackend() {
  const pythonScript = path.join(__dirname, '../../clean_api.py');
  pythonProcess = spawn('python', [pythonScript], {
    cwd: path.join(__dirname, '../../')
  });
  
  pythonProcess.stdout.on('data', (data) => {
    console.log('Python Backend:', data.toString());
  });
  
  pythonProcess.stderr.on('data', (data) => {
    console.error('Python Backend Error:', data.toString());
  });
}

app.whenReady().then(() => {
  startPythonBackend();
  createWindow();
  
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

// IPC handlers for Python backend communication
ipcMain.handle('python-call', async (event, { method, args }) => {
  // This will forward calls to our Python backend
  return new Promise((resolve, reject) => {
    // Implementation will call Python functions via HTTP or direct spawn
    resolve({ success: true, data: null });
  });
});