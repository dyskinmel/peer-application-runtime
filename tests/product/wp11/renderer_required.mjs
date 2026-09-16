import assert from 'node:assert/strict';import {existsSync} from 'node:fs';
assert.ok(existsSync('product/wp11/src/renderer.ts'),'A real renderer must be included in the deliverable, not only screenshots or a previous report');
