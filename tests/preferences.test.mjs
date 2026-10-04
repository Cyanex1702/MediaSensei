import { test, afterEach } from 'node:test';
import { strict as assert } from 'node:assert';
import { readPreference, readStringList, writePreference } from '../lib/preferences.ts';
const descriptor = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
afterEach(() => {
  if (descriptor) Object.defineProperty(globalThis, 'localStorage', descriptor);
  else delete globalThis.localStorage;
});
test('disabled storage does not crash reading or saving preferences', () => {
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, get() { throw new Error('disabled'); } });
  assert.equal(readPreference('theme'), null);
  assert.deepEqual(readStringList('favorites'), []);
  assert.doesNotThrow(() => writePreference('theme', 'forest'));
});
test('old, malformed and wrong-shape lists cannot crash render', () => {
  for (const [raw, expected] of [['{', []], ['null', []], ['{}', []], ['42', []], ['["profile",null,5]', ['profile']]]) {
    Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: { getItem: () => raw } });
    assert.deepEqual(readStringList('favorites'), expected);
  }
});
test('a full storage quota does not turn a successful API operation into failure', () => {
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: { setItem() { throw new Error('quota'); } } });
  assert.doesNotThrow(() => writePreference('recent', '["profile"]'));
});
