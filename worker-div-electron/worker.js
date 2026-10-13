// Only this worker owns the editable document and selection.
let text = ''
let cursor = 0
let anchor = 0
let sequence = 0
let initialized = false

self.onmessage = ({data}) => {
  try {
    if (data.sequence !== sequence + 1) throw new Error('Out-of-order input')
    sequence = data.sequence
    if (data.type === 'initialize') {
      if (initialized || typeof data.text !== 'string') throw new Error('Invalid initialization')
      text = data.text
      cursor = anchor = text.length
      initialized = true
    } else {
      if (!initialized) throw new Error('Input before initialization')
      if (data.type === 'select-all') {
        anchor = 0
        cursor = text.length
      } else if (data.type === 'insert' || data.type === 'backspace') {
        let start = Math.min(cursor, anchor)
        const end = Math.max(cursor, anchor)
        if (data.type === 'backspace' && start === end) start = Math.max(0, start - 1)
        const inserted = data.type === 'insert' ? data.text : ''
        if (typeof inserted !== 'string') throw new Error('Invalid text')
        text = text.slice(0, start) + inserted + text.slice(end)
        cursor = anchor = start + inserted.length
      } else if (data.type === 'left' || data.type === 'right') {
        cursor = Math.max(0, Math.min(text.length, cursor + (data.type === 'left' ? -1 : 1)))
        anchor = cursor
      } else if (data.type !== 'save') {
        throw new Error('Unknown input')
      }
    }
    const lineStart = cursor === 0 ? 0 : text.lastIndexOf('\n', cursor - 1) + 1
    self.postMessage({sequence, type: data.type, text,
      row: text.slice(0, cursor).split('\n').length - 1, column: cursor - lineStart})
  } catch (error) {
    self.postMessage({sequence, error: error.message})
  }
}
