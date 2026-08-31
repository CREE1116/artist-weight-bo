const { app, BrowserWindow } = require('electron');
const { spawn } = require('node:child_process');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');

let serverProcess = null;
let mainWindow = null;
const PORT = 8787;

const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
}
app.on('second-instance', () => {
  if (mainWindow) {
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.focus();
  }
});

function sourcePath(...parts) {
  return app.isPackaged
    ? path.join(process.resourcesPath, 'app.asar.unpacked', ...parts)
    : path.join(__dirname, '..', ...parts);
}

// data/danbooru-wiki.sqlite3 is sqlite — it must live outside app.asar (sqlite
// can't open a file inside the asar archive), so it's shipped via extraResources
// straight into Contents/Resources, not asarUnpack.
function resourcePath(...parts) {
  return app.isPackaged
    ? path.join(process.resourcesPath, ...parts)
    : path.join(__dirname, '..', ...parts);
}

function getPythonPath() {
  const venvPython = sourcePath('.venv', 'bin', 'python3');
  if (fs.existsSync(venvPython)) return venvPython;
  if (process.env.STYLEGEN_PYTHON && fs.existsSync(process.env.STYLEGEN_PYTHON)) {
    return process.env.STYLEGEN_PYTHON;
  }
  const candidates = ['/opt/homebrew/bin/python3', '/usr/local/bin/python3', '/usr/bin/python3'];
  for (const p of candidates) {
    if (fs.existsSync(p)) return p;
  }
  return 'python3';
}

function startServer() {
  const python = getPythonPath();
  const extraPath = ['/opt/homebrew/bin', '/opt/homebrew/sbin', '/usr/local/bin', '/usr/bin', '/bin', process.env.PATH]
    .filter(Boolean).join(':');
  const workDir = app.isPackaged ? path.join(app.getPath('userData'), 'work') : sourcePath('work');
  // config.json holds the (plaintext, local-only) NovelAI token and settings.
  // It must live outside the .app bundle: writing inside Contents/Resources
  // gets wiped on every rebuild/reinstall and can trip code-signing checks.
  const configPath = app.isPackaged ? path.join(app.getPath('userData'), 'config.json') : sourcePath('config.json');

  serverProcess = spawn(python, [sourcePath('main.py'), '--work', workDir, '--config', configPath], {
    cwd: sourcePath(),
    env: {
      ...process.env,
      PATH: extraPath,
      PYTHONDONTWRITEBYTECODE: '1',
      PYTHONUNBUFFERED: '1',
      NO_BROWSER: '1',
      ARTISTBO_WIKI_DB: resourcePath('data', 'danbooru-wiki.sqlite3'),
    },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  serverProcess.stdout.on('data', (d) => process.stdout.write(`[server] ${d}`));
  serverProcess.stderr.on('data', (d) => process.stderr.write(`[server] ${d}`));
  serverProcess.on('error', (err) => console.error('failed to spawn python server:', err));
}

function waitForServer(retries = 60) {
  return new Promise((resolve, reject) => {
    const attempt = (n) => {
      const req = http.get({ host: '127.0.0.1', port: PORT, path: '/state', timeout: 1000 }, (res) => {
        res.resume();
        resolve();
      });
      req.on('error', () => {
        if (n <= 0) return reject(new Error('server did not start in time'));
        setTimeout(() => attempt(n - 1), 500);
      });
      req.on('timeout', () => { req.destroy(); if (n <= 0) reject(new Error('server timeout')); else setTimeout(() => attempt(n - 1), 500); });
    };
    attempt(retries);
  });
}

async function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1100,
    height: 900,
    title: 'Artist Weight BO',
    webPreferences: { contextIsolation: true, nodeIntegration: false },
  });
  try {
    await waitForServer();
  } catch (err) {
    console.error(err);
  }
  mainWindow.loadURL(`http://127.0.0.1:${PORT}/`);
}

app.whenReady().then(() => {
  startServer();
  createWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

app.on('before-quit', () => {
  if (serverProcess) serverProcess.kill();
});
