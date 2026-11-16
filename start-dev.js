const { spawn } = require('child_process');
const path = require('path');

const nextBin = path.join(__dirname, 'node_modules', 'next', 'dist', 'bin', 'next');

process.on('SIGINT', () => {});
process.on('SIGBREAK', () => {});
process.on('SIGTERM', () => {});

function start() {
  console.log('[Dev Supervisor] Spawning Next.js dev server...');
  const child = spawn(process.execPath, [nextBin, 'dev', '-p', '3000'], {
    cwd: __dirname,
    detached: true,
    stdio: ['ignore', 'inherit', 'inherit'],
    env: { ...process.env, CI: '1', NEXT_TELEMETRY_DISABLED: '1' }
  });

  child.on('exit', (code, signal) => {
    console.log(`[Dev Supervisor] Next.js exited with code ${code}, signal ${signal}. Restarting in 2s...`);
    setTimeout(start, 2000);
  });
}

// Keep event loop alive indefinitely
setInterval(() => {}, 1000 * 60 * 60);

start();

