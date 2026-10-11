import { test } from 'node:test';
import assert from 'node:assert/strict';
import { pageWindow, pageForIndex } from '../src/pagination.ts';

test('page boundaries: empty, exact full page, partial last page', () => {
  assert.deepEqual(pageWindow(0,10,0), {page:0,pageCount:1,start:0,end:0});
  assert.deepEqual(pageWindow(10,10,0), {page:0,pageCount:1,start:0,end:10});
  assert.deepEqual(pageWindow(31,15,2), {page:2,pageCount:3,start:30,end:31});
});
test('clamps stale pages when a smaller analysis is shown', () => {
  assert.deepEqual(pageWindow(12,10,99), {page:1,pageCount:2,start:10,end:12});
});
test('changing size retains first visible row; evidence can cross pages', () => {
  const before = pageWindow(40,10,2);
  const after = pageWindow(40,15,pageForIndex(before.start,15));
  assert.ok(before.start >= after.start && before.start < after.end);
  assert.equal(pageForIndex(10,10),1);
  assert.equal(pageForIndex(39,15),2);
});
test('a large count still requests only 10 or 15 visible rows', () => {
  for (const size of [10,15]) {
    const window = pageWindow(1_000_000,size,4321);
    assert.equal(window.end-window.start,size);
    assert.equal(pageWindow(1_000_000,size,999999).end,1_000_000);
  }
});
