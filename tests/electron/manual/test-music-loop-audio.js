/* Real Chromium audio regression; run with app/node_modules/electron/dist/electron.exe
 * tests/electron/manual/test-music-loop-audio.js. Uses an isolated profile and a
 * continuous 45-second tone, with an early repeat point. No user project needed.
 * Each run retains timing samples and status under app/scratch/music-loop-audio/<timestamp>.
 */
const { app, BrowserWindow } = require('electron')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')

const root = path.resolve(__dirname, '../../..')
const output = path.join(root, 'app/scratch/music-loop-audio', new Date().toISOString().replace(/[:.]/g, '-'))
fs.mkdirSync(output, { recursive: true })
app.setPath('userData', path.join(output, 'profile'))
app.commandLine.appendSwitch('autoplay-policy', 'no-user-gesture-required')
const moduleUrl = 'data:text/javascript;base64,' + fs.readFileSync(
  path.join(root, 'app/frontend/src/shared/audio/musicLoopPlayer.js')).toString('base64')

app.whenReady().then(async () => {
  const window = new BrowserWindow({ show: false, webPreferences: { backgroundThrottling: false } })
  try {
    await window.loadURL('data:text/html,<title>Music loop audio regression</title>')
    const result = await window.webContents.executeJavaScript(`(async () => {
      const { createMusicLoopPlayer } = await import(${JSON.stringify(moduleUrl)})
      const context = new AudioContext({sampleRate: 32000})
      const buffer = context.createBuffer(1, 45 * 32000, 32000)
      const pcm = buffer.getChannelData(0)
      for (let i = 0; i < pcm.length; i++) pcm[i] = .35 * Math.sin(i * 2 * Math.PI * 440 / 32000)
      const analyser = context.createAnalyser()
      analyser.fftSize = 2048
      const gain = context.createGain.bind(context)
      context.createGain = () => {const node = gain(); node.connect(analyser); return node}
      const player = createMusicLoopPlayer(context, buffer, {loopStart: 1.5, volume: .3})
      const delay = ms => new Promise(resolve => setTimeout(resolve, ms))
      const data = new Float32Array(analyser.fftSize)
      const rms = () => {analyser.getFloatTimeDomainData(data); return Math.sqrt(data.reduce((s,x)=>s+x*x,0)/data.length)}
      const wraps = []
      for (let repeat = 0; repeat < 3; repeat++) {
        const requestedAt = {wallTime:performance.now(), contextTime:context.currentTime, state:context.state}
        await player.play(44)
        const startedAt = {wallTime:performance.now(), contextTime:context.currentTime, state:context.state}
        const samples = []
        // Chromium may report "running" before the audio device starts its
        // clock. Measure rendered audio, not an arbitrary wall-time warm-up.
        // Keep those startup samples as diagnostics and bound a stalled clock.
        while (context.currentTime - startedAt.contextTime < 1.5 && performance.now() - startedAt.wallTime < 5000) {
          await delay(25)
          samples.push({rms:rms(), wallTime:performance.now(), contextTime:context.currentTime,
            position:player.position(), state:context.state, outputTimestamp:context.getOutputTimestamp()})
        }
        const rendered = samples.filter(sample => sample.contextTime - startedAt.contextTime >= analyser.fftSize / context.sampleRate)
        wraps.push({requestedAt, startedAt, samples, position:player.position(),
          renderedSeconds:context.currentTime - startedAt.contextTime,
          beforeWrapSamples:rendered.filter(sample=>sample.position >= 44).length,
          afterWrapSamples:rendered.filter(sample=>sample.position < 44).length,
          minimumRms:Math.min(...rendered.map(sample=>sample.rms))})
      }
      player.pause()
      const pausedPosition = player.position()
      await delay(150)
      const paused = {rms:rms(), position:player.position(), expected:pausedPosition}
      await player.play()
      await Promise.all([player.seek(5), player.seek(7), player.seek(9)])
      await delay(150)
      const sought = {position:player.position(), rms:rms()}
      player.setLoopStart(2.5)
      await player.seek(44)
      await delay(1500)
      const adjusted = {position:player.position(), rms:rms()}
      player.dispose()
      await context.close()
      return {wraps, paused, sought, adjusted}
    })()`, true)
    fs.writeFileSync(path.join(output, 'result.json'), JSON.stringify(result, null, 2))
    for (const wrap of result.wraps) {
      assert.ok(wrap.renderedSeconds >= 1.5, 'audio clock must start and advance within five seconds')
      assert.ok(wrap.beforeWrapSamples >= 5 && wrap.afterWrapSamples >= 5, 'observe both sides of the actual loop boundary')
      assert.ok(wrap.position >= 1.5 && wrap.position < 3)
      assert.ok(wrap.minimumRms > .03, 'continuous tone must remain audible through repeat')
    }
    assert.equal(result.paused.position, result.paused.expected)
    assert.equal(result.paused.rms, 0)
    assert.ok(result.sought.position >= 9 && result.sought.position < 10)
    assert.ok(result.sought.rms > .03)
    assert.ok(result.adjusted.position >= 2.5 && result.adjusted.position < 4)
    assert.ok(result.adjusted.rms > .03)
    fs.writeFileSync(path.join(output, 'status.json'), JSON.stringify({passed:true}))
    app.exit(0)
  } catch (error) {
    fs.writeFileSync(path.join(output, 'status.json'), JSON.stringify({passed:false, error:error.stack}))
    app.exit(1)
  } finally {
    if (!window.isDestroyed()) window.destroy()
  }
})
