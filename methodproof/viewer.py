"""Local session viewer — HTTP server + D3 graph visualization."""

import json
import re
import webbrowser
from functools import partial
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from methodproof import store

_session_id = ""

# KINMYAKU dark theme
_HTML = """<!DOCTYPE html>
<html><head>
<meta charset="utf-8"><title>MethodProof</title>
<script src="https://d3js.org/d3.v7.min.js"></script>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { background: #12110f; color: #e0dbd0; font-family: 'IBM Plex Mono', monospace; }
.header { padding: 1rem 2rem; border-bottom: 1px solid #2a2825; display: flex; gap: 2rem; align-items: center; }
.header h1 { font-size: 1.1rem; color: #c9a84c; }
.header .stat { font-size: 0.75rem; color: #8a857a; }
.header .stat b { color: #e0dbd0; }
.main { display: flex; height: calc(100vh - 3.5rem); }
.sidebar { width: 280px; border-right: 1px solid #2a2825; padding: 1rem; overflow-y: auto; }
.sidebar h2 { font-size: 0.7rem; text-transform: uppercase; color: #8a857a; margin-bottom: 0.5rem; }
.moment { padding: 0.5rem; margin-bottom: 0.5rem; border: 1px solid #2a2825; font-size: 0.75rem; }
.moment .time { color: #8a857a; }
.graph { flex: 1; position: relative; }
canvas { width: 100%; height: 100%; }
.tooltip { position: absolute; background: #1c1a17; border: 1px solid #c9a84c; padding: 0.5rem;
  font-size: 0.7rem; max-width: 300px; pointer-events: none; display: none; }
.legend { position: absolute; bottom: 1rem; left: 1rem; font-size: 0.65rem; }
.legend span { display: inline-block; width: 10px; height: 10px; margin-right: 4px; border-radius: 50%; }
.timeline { height: 60px; border-top: 1px solid #2a2825; padding: 0 2rem; position: relative; }
.timeline .tick { position: absolute; width: 3px; bottom: 10px; border-radius: 1px; }
</style></head><body>
<div class="header">
  <h1>MethodProof</h1>
  <div class="stat" id="stats"></div>
</div>
<div class="main">
  <div class="sidebar" id="sidebar"><h2>Moments</h2><div id="moments">Loading...</div></div>
  <div class="graph"><canvas id="canvas"></canvas><div class="tooltip" id="tip"></div>
    <div class="legend" id="legend"></div>
  </div>
</div>
<div class="timeline" id="timeline"></div>
<script>
// KINMYAKU palette: gold = AI, aged gold = code, ember = terminal, cream = browser, dim = passive
const COLORS = {
  // AI actions — bright gold (the vein)
  llm_prompt:'#c9a84c',llm_completion:'#c9a84c',
  user_prompt:'#c9a84c',tool_call:'#9a7b3a',tool_result:'#9a7b3a',
  agent_launch:'#c9a84c',agent_complete:'#9a7b3a',
  ai_cli_start:'#c9a84c',ai_cli_end:'#9a7b3a',
  // Inline completions — gold spectrum
  inline_completion_shown:'#9a7b3a',inline_completion_accepted:'#c9a84c',
  inline_completion_rejected:'#6b5528',
  // File operations — aged gold (the rock around the vein)
  file_edit:'#9a7b3a',file_create:'#b8943f',file_delete:'#6b5528',
  git_commit:'#b8943f',
  // Terminal — ember (the furnace)
  terminal_cmd:'#8b8171',test_run:'#8b8171',
  // Browser — cream/dim (the surface)
  web_search:'#e0dbd0',web_visit:'#8b8171',
  browser_search:'#e0dbd0',browser_visit:'#8b8171',
  browser_copy:'#9a7b3a',browser_tab_switch:'#6b5528',browser_ai_chat:'#c9a84c',
  // Tasks
  task_created:'#9a7b3a',task_completed:'#9a7b3a',
  claude_session_start:'#6b5528',claude_code_event:'#6b5528',
};
// Edges: NEXT is ember trace, causal links are gold
const EDGE_COLORS = {NEXT:'#3d3118',RECEIVED:'#c9a84c',INFORMED:'#9a7b3a',LED_TO:'#9a7b3a',PASTED_FROM:'#6b5528',SENT_TO:'#9a7b3a',CONSUMED:'#9a7b3a',PRODUCED:'#6b5528',MODIFIED:'#6b5528'};
const SID = new URLSearchParams(location.search).get('session') || '';

async function load() {
  const [graph, stats] = await Promise.all([
    fetch('/api/sessions/'+SID+'/graph').then(r=>r.json()),
    fetch('/api/sessions/'+SID+'/stats').then(r=>r.json()),
  ]);
  document.getElementById('stats').innerHTML =
    `<b>${stats.total_events}</b> events &middot; <b>${stats.duration}</b> &middot; `+
    `<b>${graph.edges.length}</b> links`;

  // Legend
  const types = [...new Set(graph.nodes.map(n=>n.label))];
  document.getElementById('legend').innerHTML = types.map(t=>
    `<span style="background:${COLORS[t]||'#555'}"></span>${t.replace(/_/g,' ')}`
  ).join(' &nbsp; ');

  // Timeline
  if (graph.nodes.length) {
    const tl = document.getElementById('timeline');
    const ts = graph.nodes.map(n=>n.properties.timestamp);
    const min = Math.min(...ts), range = Math.max(...ts)-min || 1;
    graph.nodes.forEach(n=>{
      const el = document.createElement('div');
      el.className = 'tick';
      el.style.left = ((n.properties.timestamp-min)/range*100)+'%';
      el.style.height = '30px';
      el.style.background = COLORS[n.label]||'#555';
      tl.appendChild(el);
    });
  }

  // D3 force graph
  const canvas = document.getElementById('canvas');
  const ctx = canvas.getContext('2d');
  const W = canvas.parentElement.clientWidth, H = canvas.parentElement.clientHeight;
  canvas.width = W; canvas.height = H;

  const nodeMap = new Map(graph.nodes.map(n=>[n.id, {...n, x: W/2, y: H/2}]));
  const links = graph.edges.filter(e=>nodeMap.has(e.source)&&nodeMap.has(e.target))
    .map(e=>({source:nodeMap.get(e.source),target:nodeMap.get(e.target),type:e.type}));
  const nodes = [...nodeMap.values()];

  const sim = d3.forceSimulation(nodes)
    .force('link', d3.forceLink(links).id(d=>d.id).distance(40))
    .force('charge', d3.forceManyBody().strength(-80))
    .force('center', d3.forceCenter(W/2, H/2))
    .force('collision', d3.forceCollide(12))
    .on('tick', draw);

  function draw() {
    ctx.clearRect(0,0,W,H);
    links.forEach(l=>{
      ctx.strokeStyle = EDGE_COLORS[l.type]||'#2a2825';
      ctx.lineWidth = l.type==='NEXT'?0.5:1.5;
      ctx.beginPath(); ctx.moveTo(l.source.x,l.source.y);
      ctx.lineTo(l.target.x,l.target.y); ctx.stroke();
    });
    nodes.forEach(n=>{
      ctx.fillStyle = COLORS[n.label]||'#555';
      ctx.beginPath(); ctx.arc(n.x,n.y,5,0,Math.PI*2); ctx.fill();
    });
  }

  // Tooltip on hover
  const tip = document.getElementById('tip');
  canvas.addEventListener('mousemove', e=>{
    const r = canvas.getBoundingClientRect();
    const mx = e.clientX-r.left, my = e.clientY-r.top;
    const hit = nodes.find(n=>Math.hypot(n.x-mx,n.y-my)<8);
    if (hit) {
      tip.style.display='block'; tip.style.left=(e.clientX+10)+'px'; tip.style.top=(e.clientY+10)+'px';
      const meta = hit.properties.metadata||{};
      const keys = Object.keys(meta).slice(0,5).map(k=>`<b>${k}</b>: ${String(meta[k]).slice(0,80)}`);
      tip.innerHTML = `<b>${hit.label}</b><br>${keys.join('<br>')}`;
    } else { tip.style.display='none'; }
  });

  // Drag
  d3.select(canvas).call(d3.drag()
    .subject(e=>{const r=canvas.getBoundingClientRect();
      return nodes.find(n=>Math.hypot(n.x-(e.x-r.left),n.y-(e.y-r.top))<10)})
    .on('start',e=>{if(!e.active)sim.alphaTarget(0.3).restart();e.subject.fx=e.subject.x;e.subject.fy=e.subject.y})
    .on('drag',e=>{e.subject.fx=e.x;e.subject.fy=e.y})
    .on('end',e=>{if(!e.active)sim.alphaTarget(0);e.subject.fx=null;e.subject.fy=null}));

  // Sidebar: no moments in local mode, show event type breakdown
  document.getElementById('moments').innerHTML = Object.entries(stats.by_type||{})
    .sort((a,b)=>b[1]-a[1])
    .map(([t,c])=>`<div class="moment"><b>${c}</b> ${t.replace(/_/g,' ')}</div>`)
    .join('');
}
load();
</script></body></html>"""


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:
        pass  # suppress access logs

    def do_GET(self) -> None:
        if self.path == "/" or self.path.startswith("/?"):
            self._html(_HTML)
        elif self.path.startswith("/api/sessions/") and self.path.endswith("/graph"):
            sid = self.path.split("/")[3]
            self._json(store.get_graph(sid))
        elif self.path.startswith("/api/sessions/") and self.path.endswith("/stats"):
            sid = self.path.split("/")[3]
            self._json(_stats(sid))
        elif self.path == "/api/sessions":
            self._json(store.list_sessions())
        else:
            self.send_error(404)

    def _json(self, data: Any) -> None:
        body = json.dumps(data, default=str).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _html(self, html: str) -> None:
        body = html.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(body)


def _stats(session_id: str) -> dict[str, Any]:
    session = store.get_session(session_id)
    events = store.get_events(session_id)
    by_type: dict[str, int] = {}
    for e in events:
        by_type[e["type"]] = by_type.get(e["type"], 0) + 1
    duration = "--:--"
    if session and session.get("completed_at") and session.get("created_at"):
        secs = int(session["completed_at"] - session["created_at"])
        duration = f"{secs // 60}:{secs % 60:02d}"
    return {
        "total_events": len(events),
        "duration": duration,
        "by_type": by_type,
    }


def serve(session_id: str, port: int = 9876) -> None:
    global _session_id
    _session_id = session_id
    url = f"http://localhost:{port}/?session={session_id}"
    print(f"Viewer: {url}")
    webbrowser.open(url)
    server = HTTPServer(("127.0.0.1", port), _Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    server.server_close()
