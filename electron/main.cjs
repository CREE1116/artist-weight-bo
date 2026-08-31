const { app, BrowserWindow } = require('electron');
const { spawn, execFileSync } = require('node:child_process');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');

const IS_WIN = process.platform === 'win32';

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
  const venvPython = IS_WIN ? sourcePath('.venv', 'Scripts', 'python.exe') : sourcePath('.venv', 'bin', 'python3');
  if (fs.existsSync(venvPython)) return venvPython;
  if (process.env.STYLEGEN_PYTHON && fs.existsSync(process.env.STYLEGEN_PYTHON)) {
    return process.env.STYLEGEN_PYTHON;
  }
  // Filesystem existsSync guessing doesn't generalize across OS python installers
  // (pyenv, Microsoft Store, python.org, homebrew, ...), so actually try running
  // each PATH candidate and see what responds.
  const candidates = IS_WIN ? ['python', 'py'] : ['python3', 'python'];
  for (const cmd of candidates) {
    try {
      execFileSync(cmd, ['--version'], { stdio: 'ignore' });
      return cmd;
    } catch { /* try next */ }
  }
  return candidates[0];
}

function extraPathEnv() {
  if (IS_WIN) return process.env.PATH || '';
  return ['/opt/homebrew/bin', '/opt/homebrew/sbin', '/usr/local/bin', '/usr/bin', '/bin', process.env.PATH]
    .filter(Boolean).join(':');
}

function ensureDeps(python) {
  try {
    execFileSync(python, ['-c', 'import torch, numpy, PIL'], { stdio: 'ignore', env: { ...process.env, PATH: extraPathEnv() } });
    return true;
  } catch {
    return false;
  }
}

function installDeps(python, onLine) {
  return new Promise((resolve, reject) => {
    const proc = spawn(python, ['-m', 'pip', 'install', '-r', sourcePath('requirements.txt')], {
      cwd: sourcePath(),
      env: { ...process.env, PATH: extraPathEnv() },
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    proc.stdout.on('data', (d) => onLine(d.toString()));
    proc.stderr.on('data', (d) => onLine(d.toString()));
    proc.on('error', reject);
    proc.on('exit', (code) => (code === 0 ? resolve() : reject(new Error(`pip install exited with code ${code}`))));
  });
}

function startServer() {
  const python = getPythonPath();
  const extraPath = extraPathEnv();
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

const LOADING_HTML = `data:text/html,${encodeURIComponent(`<!doctype html><html><body style="background:#0b0d12;color:#eef1f7;font-family:-apple-system,sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;">
<div style="max-width:520px;"><h2 id="title">Preparing…</h2><pre id="log" style="white-space:pre-wrap;font-size:11px;color:#858d9e;max-height:50vh;overflow:auto;"></pre></div>
</body></html>`)}`;

function appendLog(text) {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  const escaped = JSON.stringify(text);
  mainWindow.webContents.executeJavaScript(
    `document.getElementById('log') && (document.getElementById('log').textContent += ${escaped})`
  ).catch(() => {});
}

function setTitle(text) {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  mainWindow.webContents.executeJavaScript(
    `document.getElementById('title') && (document.getElementById('title').textContent = ${JSON.stringify(text)})`
  ).catch(() => {});
}

async function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1100,
    height: 900,
    title: 'Artist Weight BO',
    webPreferences: { contextIsolation: true, nodeIntegration: false },
  });
  await mainWindow.loadURL(LOADING_HTML);

  const python = getPythonPath();
  if (!ensureDeps(python)) {
    setTitle('Python 의존성 설치 중… (첫 실행에만, 몇 분 걸릴 수 있음)');
    try {
      await installDeps(python, appendLog);
    } catch (err) {
      setTitle('의존성 설치 실패');
      appendLog(`\n${err.message}\n\npython3 + pip이 설치되어 있는지 확인하고 앱을 다시 실행해주세요.`);
      return;
    }
  }

  setTitle('서버 시작 중…');
  startServer();
  try {
    await waitForServer();
  } catch (err) {
    setTitle('서버 시작 실패');
    appendLog(`\n${err.message}`);
    return;
  }
  mainWindow.loadURL(`http://127.0.0.1:${PORT}/`);
}

app.whenReady().then(() => {
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
