import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import { renderMarkdown } from '../markdownRenderer.js'

describe('markdownRenderer', () => {
  it('renders markdown tables as semantic html tables', () => {
    const html = renderMarkdown(`
角色分布

| 角色 | 调用次数 | tokens | 成本 |
| --- | --- | --- | --- |
| 进攻教练 | 1 | 0 | $0.000 |
| 防守教练 | 1 | 0 | $0.000 |
`)

    assert.match(html, /<table class="md-table">/)
    assert.match(html, /<th>角色<\/th>/)
    assert.match(html, /<td>进攻教练<\/td>/)
    assert.match(html, /<td>\$0\.000<\/td>/)
    assert.doesNotMatch(html, /\| 角色 \|/)
  })

  it('keeps underscore-heavy scenario keys intact inside tables', () => {
    const html = renderMarkdown(`
| 场景 | xG |
| --- | --- |
| 双方正常发挥（home_normal_away_normal） | 1.61-0.85 |
`)

    assert.match(html, /home_normal_away_normal/)
    assert.doesNotMatch(html, /home<em>normal<\/em>/)
  })

  it('strips the leading section heading when requested', () => {
    const html = renderMarkdown('## 胜平负与比分判断\n\n- 主胜概率：55%')

    assert.doesNotMatch(html, /胜平负与比分判断/)
    assert.match(html, /主胜概率/)
  })
})
