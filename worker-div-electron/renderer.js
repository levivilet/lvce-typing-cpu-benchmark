const editorElement = document.querySelector('#editor')
const text = document.querySelector('#text')
const cursor = document.querySelector('#cursor')
const textNode = document.createTextNode('')
text.appendChild(textNode)
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
let viewportWidth = editorElement.clientWidth
let viewportHeight = editorElement.clientHeight
let scrollLeft = 0
let scrollTop = 0
editorElement.addEventListener('scroll', () => {
  scrollLeft = editorElement.scrollLeft
  scrollTop = editorElement.scrollTop
})
new ResizeObserver(() => {
  viewportWidth = editorElement.clientWidth
  viewportHeight = editorElement.clientHeight
}).observe(editorElement)

function revealCursor(column, row) {
  const x = 16 + column * characterWidth
  const y = 16 + row * 20
  const nextLeft = x < scrollLeft + 16 ? Math.max(0, x - 16)
    : x + 1 > scrollLeft + viewportWidth - 16 ? x + 1 - viewportWidth + 16 : scrollLeft
  const nextTop = y < scrollTop + 16 ? Math.max(0, y - 16)
    : y + 20 > scrollTop + viewportHeight - 16 ? y + 20 - viewportHeight + 16 : scrollTop
  // Geometry is already known from the worker. Avoid forcing layout on every
  // keystroke; write scroll offsets only when the cursor leaves the viewport.
  if (nextLeft !== scrollLeft) editorElement.scrollLeft = scrollLeft = nextLeft
  if (nextTop !== scrollTop) editorElement.scrollTop = scrollTop = nextTop
}

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
  if (data.text.startsWith(textNode.data)) {
    textNode.appendData(data.text.slice(textNode.length))
  } else {
    textNode.data = data.text
  }
  cursor.style.transform = `translate(${data.column * characterWidth}px, ${data.row * 20}px)`
  revealCursor(data.column, data.row)
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
