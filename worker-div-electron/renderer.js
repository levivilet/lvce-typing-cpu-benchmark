const editorElement = document.querySelector('#editor')
const text = document.querySelector('#text')
const cursor = document.querySelector('#cursor')
const worker = new Worker('worker.js')
let sequence = 0
let acknowledged = 0
let ready = false
let failed = false
let saves = Promise.resolve()
const canvas = document.createElement('canvas')
const context = canvas.getContext('2d')
context.font = getComputedStyle(editorElement).font
const characterWidth = context.measureText('M').width

function fail(error) {
  failed = true
  editorElement.dataset.error = String(error)
  console.error(error)
}
function send(type, contents) {
  worker.postMessage({sequence: ++sequence, type, text: contents})
}
worker.onerror = (event) => fail(event.message)
worker.onmessage = ({data}) => {
  if (failed) return
  if (data.error) return fail(data.error)
  if (data.sequence !== acknowledged + 1) return fail('Out-of-order response')
  acknowledged = data.sequence
  text.textContent = data.text
  cursor.style.transform = `translate(${data.column * characterWidth}px, ${data.row * 20}px)`
  editorElement.dataset.sequence = String(acknowledged)
  if (data.type === 'initialize') {
    ready = true
    editorElement.dataset.ready = 'true'
    editorElement.focus()
  }
  if (data.type === 'save') {
    // A save response snapshots all preceding input, then writes in request order.
    saves = saves.then(() => window.editor.write(data.text)).then(() => {
      editorElement.dataset.savedSequence = String(data.sequence)
    }).catch(fail)
  }
}
editorElement.addEventListener('keydown', (event) => {
  if (!ready || failed) return
  const modifier = event.ctrlKey || event.metaKey
  let type
  let contents
  if (modifier && event.key.toLowerCase() === 's') type = 'save'
  else if (modifier && event.key.toLowerCase() === 'a') type = 'select-all'
  else if (!modifier && !event.altKey) {
    if (event.key === 'Backspace') type = 'backspace'
    else if (event.key === 'ArrowLeft') type = 'left'
    else if (event.key === 'ArrowRight') type = 'right'
    else if (event.key === 'Enter') { type = 'insert'; contents = '\n' }
    else if (event.key.length === 1) { type = 'insert'; contents = event.key }
  }
  if (type) {
    event.preventDefault()
    send(type, contents)
  }
})
window.editor.read().then((contents) => send('initialize', contents)).catch(fail)
