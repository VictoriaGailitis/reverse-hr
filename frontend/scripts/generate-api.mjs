import { readFile, writeFile } from 'node:fs/promises';
import openapiTS, { astToString } from 'openapi-typescript';

for (const service of ['candidate', 'privacy', 'employer', 'hiring', 'matching', 'notification', 'integration', 'demo-ats', 'assessment', 'coding-workspace', 'code-runner', 'evaluation', 'media', 'whiteboard', 'proctoring', 'achievements', 'audit']) {
  const schema = JSON.parse(await readFile(new URL(`../contracts/${service}.openapi.json`, import.meta.url), 'utf8'));
  const ast = await openapiTS(schema);
  await writeFile(new URL(`../src/api/generated/${service}.ts`, import.meta.url), astToString(ast));
  console.log(`Generated ${service}`);
}
