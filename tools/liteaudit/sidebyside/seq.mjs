// Print the reflector effect objects read from RAM, frame by frame, for shine targets
// (capture.py logs them around the shot; their offset from the fighter, scale and
// animation frame are what the shine's drawing was calibrated against).
//   node seq.mjs <run folder> [id ...]      (default: every shine target in the run)
import fs from 'node:fs'; import path from 'node:path'
const [run, ...ids] = process.argv.slice(2)
if (!run) { console.error('usage: node seq.mjs <run folder> [id ...]'); process.exit(2) }
const targets = JSON.parse(fs.readFileSync(path.join(run, 'targets-ext.json'), 'utf8'))
for (const t of targets.filter(x => (ids.length ? ids.includes(x.id) : x.seq_pre))) {
  const p = path.join(run, 'shots', `${t.id}.json`)
  const m = fs.existsSync(p) ? JSON.parse(fs.readFileSync(p, 'utf8')) : null
  if (!m?.seq) { console.log(t.id, 'no seq'); continue }
  const sx = t.ports.find(q => q.port === t.subject?.port)?.x ?? 0
  console.log(`== ${t.id} (shot at ${m.frame})`)
  for (const s of m.seq) {
    const f = s.live.filter(q => q.kind === 1 || q.kind === 22).sort((a, b) => Math.abs(a.pos[0] - sx) - Math.abs(b.pos[0] - sx))[0]
    if (!f) continue
    const dir = f.facing
    const eff = (f.effects || []).filter(e => e.root_world && e.root_scale).map(e => {
      const rs = e.root_scale[0]
      const off = [(e.root_world[0] - f.pos[0]) * dir / rs, (e.root_world[1] - f.pos[1]) / rs].map(v => v.toFixed(2)).join(',')
      return `[off ${off} rs ${rs.toFixed(2)} ` + e.children.map(c => `${c.flags} s${c.scale[0].toFixed(3)}/${c.scale[1].toFixed(3)} f${c.anim_frame} rz${c.rot_z[0].toFixed(2)}`).join(' ; ') + ']'
    }).join(' ')
    const hip = f.hip ? [(f.hip[0] - f.pos[0]) * dir, f.hip[1] - f.pos[1]].map(v => v.toFixed(2)).join(',') : '-'
    console.log(String(s.match_frame).padStart(6), s.match_frame === m.frame ? '*' : ' ', 'k', f.kind, 'st', f.state, 'af', f.anim_frame, 'dir', dir, 'hip', hip, eff)
  }
}
