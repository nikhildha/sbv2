/**
 * Custom Next.js server — adds Socket.IO + chokidar file watching
 * Replaces web-dashboard/server.js for the Next.js migration
 * Port: 3001
 */

const { createServer } = require('http')
const { parse } = require('url')
const next = require('next')
const { Server } = require('socket.io')
const chokidar = require('chokidar')
const fs = require('fs')
const path = require('path')

const dev = process.env.NODE_ENV !== 'production'
const hostname = '0.0.0.0'
const port = parseInt(process.env.PORT || '3001', 10)

// Data directory — shared with Python bot
const DATA_DIR = path.join(__dirname, '..', 'data')

// Helper: safely read a JSON file
function readJson(filename, fallback = {}) {
  try {
    const filePath = path.join(DATA_DIR, filename)
    if (!fs.existsSync(filePath)) return fallback
    return JSON.parse(fs.readFileSync(filePath, 'utf8'))
  } catch {
    return fallback
  }
}

const app = next({ dev, hostname, port })
const handle = app.getRequestHandler()

app.prepare().then(() => {
  const httpServer = createServer(async (req, res) => {
    try {
      const parsedUrl = parse(req.url, true)
      await handle(req, res, parsedUrl)
    } catch (err) {
      console.error('Error handling request:', err)
      res.statusCode = 500
      res.end('Internal server error')
    }
  })

  // ── Socket.IO setup ──────────────────────────────────────────────────────
  const io = new Server(httpServer, {
    cors: { origin: '*' },
    transports: ['websocket', 'polling'],
  })

  io.on('connection', (socket) => {
    console.log(`[WS] Client connected: ${socket.id}`)

    // Send initial full state snapshot
    socket.emit('full-update', {
      state: readJson('bot_state.json'),
      multi: readJson('multi_bot_state.json'),
      scanner: readJson('scanner_state.json'),
      tradebook: readJson('tradebook.json'),
    })

    // Send last 100 log lines
    try {
      const logPath = path.join(DATA_DIR, 'bot.log')
      if (fs.existsSync(logPath)) {
        const lines = fs.readFileSync(logPath, 'utf8').split('\n').filter(Boolean).slice(-100)
        socket.emit('log-init', lines)
      }
    } catch {}

    // Client: toggle engine pause/resume
    socket.on('toggle-engine', (shouldRun) => {
      try {
        const stateFile = path.join(DATA_DIR, 'engine_state.json')
        const current = readJson('engine_state.json')
        const updated = {
          ...current,
          status: shouldRun ? 'running' : 'paused',
          paused_at: shouldRun ? null : new Date().toISOString(),
          resumed_at: shouldRun ? new Date().toISOString() : null,
          paused_by: shouldRun ? null : 'dashboard',
        }
        fs.writeFileSync(stateFile, JSON.stringify(updated, null, 2))
        io.emit('engine-status', { active: shouldRun, message: shouldRun ? 'Bot resumed' : 'Bot paused' })
      } catch (err) {
        console.error('toggle-engine error:', err)
      }
    })

    // Client: trigger manual analysis cycle
    socket.on('trigger-cycle', () => {
      try {
        fs.writeFileSync(path.join(DATA_DIR, 'force_cycle.trigger'), Date.now().toString())
        socket.emit('trigger-ack', { status: 'ok', message: 'Cycle triggered' })
      } catch (err) {
        socket.emit('trigger-ack', { status: 'error', message: err.message })
      }
    })

    socket.on('disconnect', () => {
      console.log(`[WS] Client disconnected: ${socket.id}`)
    })
  })

  // ── Chokidar file watcher ────────────────────────────────────────────────
  if (fs.existsSync(DATA_DIR)) {
    const watcher = chokidar.watch(DATA_DIR, {
      persistent: true,
      ignoreInitial: true,
      awaitWriteFinish: { stabilityThreshold: 500, pollInterval: 100 },
    })

    let lastLogSize = 0

    watcher.on('change', (filePath) => {
      const filename = path.basename(filePath)

      if (filename === 'bot_state.json') {
        io.emit('state-update', readJson('bot_state.json'))
      } else if (filename === 'multi_bot_state.json') {
        io.emit('multi-update', readJson('multi_bot_state.json'))
      } else if (filename === 'scanner_state.json') {
        io.emit('scanner-update', readJson('scanner_state.json'))
      } else if (filename === 'tradebook.json') {
        io.emit('tradebook-update', readJson('tradebook.json'))
      } else if (filename === 'trade_log.csv') {
        io.emit('trades-update', { timestamp: new Date().toISOString() })
      } else if (filename === 'bot.log') {
        // Stream only new lines
        try {
          const stat = fs.statSync(filePath)
          if (stat.size > lastLogSize) {
            const fd = fs.openSync(filePath, 'r')
            const buffer = Buffer.alloc(stat.size - lastLogSize)
            fs.readSync(fd, buffer, 0, buffer.length, lastLogSize)
            fs.closeSync(fd)
            const newLines = buffer.toString('utf8').split('\n').filter(Boolean)
            newLines.forEach((line) => io.emit('log-line', line))
            lastLogSize = stat.size
          }
        } catch {}
      }
    })

    console.log(`[Watcher] Watching ${DATA_DIR}`)
  } else {
    console.warn(`[Watcher] Data dir not found: ${DATA_DIR} — file watching disabled`)
  }

  // ── Start server ─────────────────────────────────────────────────────────
  httpServer.listen(port, hostname, () => {
    console.log(`\n🚀 SENTINEL AI server ready`)
    console.log(`   Local:   http://localhost:${port}`)
    console.log(`   Mode:    ${dev ? 'development' : 'production'}`)
    console.log(`   Data:    ${DATA_DIR}\n`)
  })
})
