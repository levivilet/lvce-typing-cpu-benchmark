const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')

const element = {dataset: {}, style: {}, focus() {}, addEventListener(_name, callback) { this.keydown = callback }}
const text = {textContent: ''}
const cursor = {style: {}}
const writes = []
let resolveWrite
let worker
class Worker {
  constructor() {
    worker = this
    const self = {postMessage: data => this.onmessage({data})}
    this.self = self
    vm.runInNewContext(fs.readFileSync('worker-div-electron/worker.js', 'utf8'), {self})
  }
  postMessage(data) { this.self.onmessage({data}) }
}
const context = {
  Worker, console,
  getComputedStyle: () => ({font: '16px monospace'}),
  document: {
    querySelector: selector => ({'#editor': element, '#text': text, '#cursor': cursor})[selector],
    createElement: () => ({getContext: () => ({measureText: () => ({width: 10})})}),
  },
}
context.window = context
// Electron's bridge exposes a nonconfigurable property. Global lexical bindings
// must not collide with it, or the entire renderer script fails before ready.
Object.defineProperty(context, 'editor', {value: {
  read: async () => 'fixture\n',
  write: contents => {
    writes.push(contents)
    return new Promise(resolve => { resolveWrite = resolve })
  },
}, configurable: false})
vm.runInNewContext(fs.readFileSync('worker-div-electron/renderer.js', 'utf8'), context)
const tick = () => new Promise(resolve => setImmediate(resolve))
function key(key, ctrlKey = false) {
  element.keydown({key, ctrlKey, preventDefault() {}})
}
async function main() {
  await tick()
  assert.equal(element.dataset.ready, 'true')
  key('a', true); key('Backspace'); key('a'); key('b'); key('Enter'); key('c')
  assert.equal(text.textContent, 'ab\nc')
  assert.equal(cursor.style.transform, 'translate(10px, 20px)')
  key('s', true); key('d'); key('s', true)
  await tick()
  assert.deepEqual(writes, ['ab\nc'])
  resolveWrite(); await tick()
  assert.deepEqual(writes, ['ab\nc', 'ab\ncd'])
  resolveWrite(); await tick()
  assert.equal(element.dataset.savedSequence, element.dataset.sequence)
  worker.onmessage({data: {sequence: 999, text: 'corruption'}})
  assert.equal(element.dataset.error, 'Out-of-order response')
  assert.equal(text.textContent, 'ab\ncd')
  key('z'); assert.equal(text.textContent, 'ab\ncd')
}
main().catch(error => { console.error(error); process.exitCode = 1 })
