const { app, BrowserWindow, ipcMain } = require('electron');
const path = require('path');
const { spawn } = require('child_process');

let mainWindow = null;
let apiProc = null;

function startAPI() {
  const base = app.isPackaged
    ? path.join(process.resourcesPath, 'api')
    : path.join(__dirname, '..');
  apiProc = spawn('python3', [
    '-m', 'uvicorn', 'api.main:app', '--host', '127.0.0.1', '--port', '8765'
  ], { cwd: base, stdio: 'pipe', env: { ...process.env } });
  apiProc.stdout.on('data', d => console.log('[API]', d.toString().trim()));
  apiProc.stderr.on('data', d => console.error('[API]', d.toString().trim()));
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1400, height: 900,
    minWidth: 800, minHeight: 600,
    backgroundColor: '#0a0b0f',
    webPreferences: { nodeIntegration: false, contextIsolation: true }
  });
  mainWindow.loadURL('http://127.0.0.1:8765');
  mainWindow.on('closed', () => mainWindow = null);
}

app.whenReady().then(() => {
  startAPI();
  setTimeout(createWindow, 2000);
  app.on('activate', () => BrowserWindow.getAllWindows().length === 0 && createWindow());
});

app.on('window-all-closed', () => {
  if (apiProc) apiProc.kill();
  process.platform !== 'darwin' && app.quit();
});

app.on('before-quit', () => apiProc && apiProc.kill());
