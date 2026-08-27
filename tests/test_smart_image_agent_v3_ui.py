import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SHELL_PATH = ROOT / "static" / "js" / "smart-image-agent" / "v3" / "shell.js"
APP_PATH = ROOT / "static" / "js" / "smart-image-agent" / "v3" / "app.js"
CSS_PATH = ROOT / "static" / "css" / "smart-image-agent.css"


def run_node(script: str) -> str:
    with tempfile.TemporaryDirectory() as temp_dir:
        script_path = Path(temp_dir) / "v3-ui-test.cjs"
        script_path.write_text(script, encoding="utf-8")
        completed = subprocess.run(
            ["node", str(script_path)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env={**os.environ, "NODE_PATH": str(ROOT / "node_modules")},
        )
    if completed.returncode:
        raise AssertionError(completed.stderr)
    return completed.stdout


FAKE_DOM = """
class FakeNode {
  constructor(){ this.listeners={}; this.dataset={}; this.value=''; this.hidden=true; this.disabled=false; this.textContent=''; this.open=false; this.files=[]; this.innerHTML=''; }
  addEventListener(type, handler){ (this.listeners[type] ||= []).push(handler); }
  async trigger(type){ for(const handler of this.listeners[type] || []) await handler({target:this, metaKey:false, ctrlKey:false, key:''}); }
  querySelector(){ return new FakeNode(); }
  querySelectorAll(){ return []; }
  focus(){ this.focused=true; }
}
const controls = new Map();
const root = new FakeNode();
root.querySelector = selector => {
  if(!controls.has(selector)) controls.set(selector, new FakeNode());
  return controls.get(selector);
};
root.querySelectorAll = () => [];
global.document = {
  body:{classList:{add(){ }}, appendChild(){ }},
  getElementById(){ return null; },
  createElement(){ return root; }
};
global.window = global;
"""


class SmartImageAgentV3UiTests(unittest.TestCase):
    def test_empty_composer_shows_explaining_error(self):
        script = FAKE_DOM + """
const {buildSync} = require('esbuild');
const result = buildSync({entryPoints:['static/js/smart-image-agent/v3/app.js'], bundle:true, format:'iife', write:false, platform:'browser'});
global.localStorage = {data:{}, getItem(key){ return this.data[key] || ''; }, setItem(key, value){ this.data[key] = value; }, removeItem(key){ delete this.data[key]; }};
global.fetch = async () => ({ok:true, status:200, json:async()=>({id:'session-1'}), clone(){ return this; }, text:async()=>''});
global.SmartImageAgentBridge = {
  getCanvasContext:() => ({canvas_id:'canvas-1', team_id:'team-1'}),
  getSelection:() => [],
  subscribeSelection:() => () => {},
  uploadReferences:async() => [],
  runImageTask:async() => ({}),
  saveCanvas:async() => {},
  saveToAssetLibrary:async() => {},
  canvasControls:{}
};
new Function(result.outputFiles[0].text)();
(async() => {
  await global.SmartImageAgentV3App.init();
  await controls.get('[data-create]').trigger('click');
  const notice = controls.get('[data-notice]');
  if(notice.textContent !== '请先输入创作需求' || notice.hidden || !controls.get('[data-intent]').focused){
    throw new Error(JSON.stringify({text:notice.textContent, hidden:notice.hidden, focused:controls.get('[data-intent]').focused}));
  }
})();
"""
        run_node(script)

    def test_shell_emits_current_plan_and_new_requirement_labels(self):
        script = FAKE_DOM + """
const {buildSync} = require('esbuild');
const result = buildSync({entryPoints:['static/js/smart-image-agent/v3/shell.js'], bundle:true, format:'cjs', write:false, platform:'browser'});
const bundledModule = {exports:{}};
new Function('module', 'exports', result.outputFiles[0].text)(bundledModule, bundledModule.exports);
bundledModule.exports.createShell();
if(!root.innerHTML.includes('aria-label="当前方案"') || !root.innerHTML.includes('新创作需求')){
  throw new Error(root.innerHTML);
}
"""
        run_node(script)

    def test_v3_css_keeps_actual_controls_horizontal(self):
        css = CSS_PATH.read_text(encoding="utf-8")
        self.assertIn(".sia-canvas-controls button", css)
        self.assertIn("white-space:nowrap", css)
        self.assertIn(".sia-composer-controls", css)


if __name__ == "__main__":
    unittest.main()
