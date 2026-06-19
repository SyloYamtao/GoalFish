import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import {
  generatedSectionsFromSnapshot,
  reportOutlineFromSnapshot,
} from '../step5ReportSnapshot.js'

describe('step5ReportSnapshot', () => {
  it('uses the persisted report outline from the report payload', () => {
    const outline = reportOutlineFromSnapshot({
      title: 'Ignored fallback',
      outline: {
        title: 'Canada vs Bosnia Report',
        summary: 'Persisted summary',
        sections: [{ title: '执行摘要', content: '' }],
      },
    })

    assert.equal(outline.title, 'Canada vs Bosnia Report')
    assert.equal(outline.summary, 'Persisted summary')
    assert.deepEqual(outline.sections, [{ title: '执行摘要', content: '' }])
  })

  it('falls back to report metadata outline when top-level outline is absent', () => {
    const outline = reportOutlineFromSnapshot({
      report_metadata: {
        outline: {
          title: 'Metadata report',
          summary: 'Metadata summary',
          sections: [{ title: '比分概率', content: '' }],
        },
      },
    })

    assert.equal(outline.title, 'Metadata report')
    assert.equal(outline.sections[0].title, '比分概率')
  })

  it('maps persisted section rows by section index', () => {
    assert.deepEqual(
      generatedSectionsFromSnapshot([
        { section_index: 1, content: '## 执行摘要\n\nA' },
        { section_index: 3, content: '## 场景矩阵\n\nC' },
        { content: 'ignored' },
      ]),
      {
        1: '## 执行摘要\n\nA',
        3: '## 场景矩阵\n\nC',
      },
    )
  })
})
