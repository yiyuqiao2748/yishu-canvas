import { build, transform } from 'esbuild';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';

const root = path.resolve(import.meta.dirname, '..');
const outputDir = path.join(root, 'static', 'dist', 'js');
const entries = [
  ['static/js/index.js', 'index.min.js'],
  ['static/js/workbench.js', 'workbench.min.js'],
  ['static/js/canvas.js', 'canvas.min.js'],
  ['static/js/smart-canvas.js', 'smart-canvas.min.js'],
  ['static/js/smart-image-agent/app.js', 'smart-image-agent.min.js']
];

await mkdir(outputDir, { recursive: true });
for (const [sourcePath, outputName] of entries) {
  const source = await readFile(path.join(root, sourcePath), 'utf8');
  const result = await transform(source, {
    loader: 'js',
    minify: true,
    target: 'es2020',
    legalComments: 'none'
  });
  await writeFile(path.join(outputDir, outputName), result.code, 'utf8');
  console.log(`${sourcePath} -> static/dist/js/${outputName}`);
}

await build({
  entryPoints: [path.join(root, 'static', 'js', 'smart-image-agent', 'v3', 'app.js')],
  bundle: true,
  format: 'iife',
  minify: true,
  target: 'es2020',
  legalComments: 'none',
  outfile: path.join(outputDir, 'smart-image-agent-v3.min.js')
});
console.log('static/js/smart-image-agent/v3/app.js -> static/dist/js/smart-image-agent-v3.min.js');
