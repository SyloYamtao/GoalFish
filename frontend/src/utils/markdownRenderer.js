const escapeHtml = (value) => String(value ?? '')
  .replace(/&/g, '&amp;')
  .replace(/</g, '&lt;')
  .replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;')

const splitTableRow = (line) => line
  .trim()
  .replace(/^\|/, '')
  .replace(/\|$/, '')
  .split('|')
  .map(cell => cell.trim())

const isTableDivider = (line) => {
  const cells = splitTableRow(line)
  return cells.length > 1 && cells.every(cell => /^:?-{3,}:?$/.test(cell))
}

const renderMarkdownTables = (text) => {
  const lines = String(text || '').split('\n')
  const output = []

  for (let index = 0; index < lines.length; index++) {
    const header = lines[index]
    const divider = lines[index + 1]
    if (!header?.trim().startsWith('|') || !divider?.trim().startsWith('|') || !isTableDivider(divider)) {
      output.push(header)
      continue
    }

    const headers = splitTableRow(header)
    const rows = []
    index += 2
    while (index < lines.length && lines[index]?.trim().startsWith('|')) {
      rows.push(splitTableRow(lines[index]))
      index += 1
    }
    index -= 1

    output.push([
      '<div class="md-table-wrap"><table class="md-table">',
      '<thead><tr>',
      headers.map(cell => `<th>${escapeHtml(cell)}</th>`).join(''),
      '</tr></thead>',
      '<tbody>',
      rows.map(row => `<tr>${headers.map((_, cellIndex) => `<td>${escapeHtml(row[cellIndex] || '')}</td>`).join('')}</tr>`).join(''),
      '</tbody></table></div>',
    ].join(''))
  }

  return output.join('\n')
}

const protectHtmlBlocks = html => {
  const blocks = []
  const protectedHtml = html.replace(/<(pre|div) class="(?:code-block|md-table-wrap)"[\s\S]*?<\/\1>/g, block => {
    const token = `§§HTMLBLOCK${blocks.length}§§`
    blocks.push(block)
    return token
  })
  return { protectedHtml, blocks }
}

const restoreHtmlBlocks = (html, blocks) => blocks.reduce(
  (output, block, index) => output.replace(`§§HTMLBLOCK${index}§§`, block),
  html,
)

export const renderMarkdown = (content, { stripLeadingHeading = true } = {}) => {
  if (!content) return ''

  let html = String(content)
  if (stripLeadingHeading) {
    html = html.replace(/^##\s+.+\n+/, '')
  }

  html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (_match, _lang, code) => (
    `<pre class="code-block"><code>${escapeHtml(code)}</code></pre>`
  ))

  html = renderMarkdownTables(html)
  const protectedBlocks = protectHtmlBlocks(html)
  html = protectedBlocks.protectedHtml
  html = html.replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>')
  html = html.replace(/^#### (.+)$/gm, '<h5 class="md-h5">$1</h5>')
  html = html.replace(/^### (.+)$/gm, '<h4 class="md-h4">$1</h4>')
  html = html.replace(/^## (.+)$/gm, '<h3 class="md-h3">$1</h3>')
  html = html.replace(/^# (.+)$/gm, '<h2 class="md-h2">$1</h2>')
  html = html.replace(/^> (.+)$/gm, '<blockquote class="md-quote">$1</blockquote>')

  html = html.replace(/^(\s*)- (.+)$/gm, (_match, indent, text) => {
    const level = Math.floor(indent.length / 2)
    return `<li class="md-li" data-level="${level}">${text}</li>`
  })
  html = html.replace(/^(\s*)(\d+)\. (.+)$/gm, (_match, indent, _num, text) => {
    const level = Math.floor(indent.length / 2)
    return `<li class="md-oli" data-level="${level}">${text}</li>`
  })

  html = html.replace(/(<li class="md-li"[^>]*>.*?<\/li>\s*)+/g, '<ul class="md-ul">$&</ul>')
  html = html.replace(/(<li class="md-oli"[^>]*>.*?<\/li>\s*)+/g, '<ol class="md-ol">$&</ol>')
  html = html.replace(/<\/li>\s+<li/g, '</li><li')
  html = html.replace(/<ul class="md-ul">\s+/g, '<ul class="md-ul">')
  html = html.replace(/<ol class="md-ol">\s+/g, '<ol class="md-ol">')
  html = html.replace(/\s+<\/ul>/g, '</ul>')
  html = html.replace(/\s+<\/ol>/g, '</ol>')

  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
  html = html.replace(/\*(.+?)\*/g, '<em>$1</em>')
  html = html.replace(/_(.+?)_/g, '<em>$1</em>')
  html = html.replace(/^---$/gm, '<hr class="md-hr">')
  html = restoreHtmlBlocks(html, protectedBlocks.blocks)
  html = html.replace(/\n\n/g, '</p><p class="md-p">')
  html = html.replace(/\n/g, '<br>')
  html = `<p class="md-p">${html}</p>`
  html = html.replace(/<p class="md-p"><\/p>/g, '')
  html = html.replace(/<p class="md-p">(<h[2-5])/g, '$1')
  html = html.replace(/(<\/h[2-5]>)<\/p>/g, '$1')
  html = html.replace(/<p class="md-p">(<ul|<ol|<blockquote|<pre|<hr|<div class="md-table-wrap")/g, '$1')
  html = html.replace(/(<\/ul>|<\/ol>|<\/blockquote>|<\/pre>|<\/div>)<\/p>/g, '$1')
  html = html.replace(/<br>\s*(<ul|<ol|<blockquote|<div class="md-table-wrap")/g, '$1')
  html = html.replace(/(<\/ul>|<\/ol>|<\/blockquote>|<\/div>)\s*<br>/g, '$1')
  html = html.replace(/<p class="md-p">(<br>\s*)+(<ul|<ol|<blockquote|<pre|<hr|<div class="md-table-wrap")/g, '$2')
  html = html.replace(/(<br>\s*){2,}/g, '<br>')
  html = html.replace(/(<\/ol>|<\/ul>|<\/blockquote>|<\/div>)<br>(<p|<div)/g, '$1$2')

  const tokens = html.split(/(<ol class="md-ol">(?:<li class="md-oli"[^>]*>[\s\S]*?<\/li>)+<\/ol>)/g)
  let olCounter = 0
  let inSequence = false
  for (let i = 0; i < tokens.length; i++) {
    if (tokens[i].startsWith('<ol class="md-ol">')) {
      const liCount = (tokens[i].match(/<li class="md-oli"/g) || []).length
      if (liCount === 1) {
        olCounter += 1
        if (olCounter > 1) {
          tokens[i] = tokens[i].replace('<ol class="md-ol">', `<ol class="md-ol" start="${olCounter}">`)
        }
        inSequence = true
      } else {
        olCounter = 0
        inSequence = false
      }
    } else if (inSequence && /<h[2-5]/.test(tokens[i])) {
      olCounter = 0
      inSequence = false
    }
  }

  return tokens.join('')
}
