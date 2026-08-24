import { transform } from 'esbuild';
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
