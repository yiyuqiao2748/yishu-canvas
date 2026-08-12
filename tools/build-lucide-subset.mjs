import { build } from 'esbuild';
import * as lucide from 'lucide';
import { mkdir, readFile, readdir, unlink, writeFile } from 'node:fs/promises';
import path from 'node:path';

const root = path.resolve(import.meta.dirname, '..');
const staticRoot = path.join(root, 'static');
const outputDir = path.join(staticRoot, 'dist');
const generatedEntry = path.join(outputDir, '.lucide-entry.js');
const outputFile = path.join(outputDir, 'lucide-subset.js');
const sourceExtensions = new Set(['.html', '.js']);
const skippedDirectories = new Set(['dist', 'vendor']);

async function collectSourceFiles(directory) {
  const files = [];
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    if (entry.isDirectory() && skippedDirectories.has(entry.name)) continue;
    const absolute = path.join(directory, entry.name);
    if (entry.isDirectory()) files.push(...await collectSourceFiles(absolute));
    else if (sourceExtensions.has(path.extname(entry.name))) files.push(absolute);
  }
  return files;
}

function normalizedIconName(value) {
  return String(value || '').replace(/[^a-z0-9]/gi, '').toLowerCase();
}

const availableIcons = new Map();
for (const [name, value] of Object.entries(lucide)) {
  if (Array.isArray(value) && value.length) availableIcons.set(normalizedIconName(name), name);
}

const iconNames = new Set(['CircleHelp']);
const literalPattern = /["'`]([a-z][a-z0-9-]{0,48})["'`]/gi;
for (const file of await collectSourceFiles(staticRoot)) {
  const source = await readFile(file, 'utf8');
  for (const match of source.matchAll(literalPattern)) {
    const exportName = availableIcons.get(normalizedIconName(match[1]));
    if (exportName) iconNames.add(exportName);
  }
}

const sortedIcons = [...iconNames].sort();
await mkdir(outputDir, { recursive: true });
await writeFile(generatedEntry, `
import { createIcons, ${sortedIcons.join(', ')} } from 'lucide';
const icons = { ${sortedIcons.join(', ')} };
window.lucide = {
  icons,
  createIcons(options = {}) {
    return createIcons({ ...options, icons: { ...icons, ...(options.icons || {}) } });
  }
};
`, 'utf8');

await build({
  entryPoints: [generatedEntry],
  outfile: outputFile,
  bundle: true,
  minify: true,
  platform: 'browser',
  target: ['es2020'],
  legalComments: 'none'
});
await unlink(generatedEntry);

console.log(`Lucide subset: ${sortedIcons.length} icons -> ${path.relative(root, outputFile)}`);
