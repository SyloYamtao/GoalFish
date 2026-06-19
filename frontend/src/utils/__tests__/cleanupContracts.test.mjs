import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, it } from 'node:test'
import { fileURLToPath } from 'node:url'

const repoRoot = resolve(fileURLToPath(new URL('.', import.meta.url)), '../../../..')
const read = (path) => readFileSync(resolve(repoRoot, path), 'utf8')

describe('cleanup contracts', () => {
  it('keeps Process route on MainView and removes the retired Process workbench', () => {
    const router = read('frontend/src/router/index.js')

    assert.match(router, /import Process from '\.\.\/views\/MainView\.vue'/)
    assert.equal(existsSync(resolve(repoRoot, 'frontend/src/views/Process.vue')), false)
  })

  it('does not ship the retired simulation API client', () => {
    assert.equal(existsSync(resolve(repoRoot, 'frontend/src/api/simulation.js')), false)
  })

  it('keeps only active report client exports used by Step4 and Step5', () => {
    const reportClient = read('frontend/src/api/report.js')

    for (const activeExport of [
      'getAgentLog',
      'getConsoleLog',
      'getReport',
      'getReportSections',
      'createReportConversation',
      'getReportConversationMessages',
      'sendReportConversationMessage',
    ]) {
      assert.match(reportClient, new RegExp(`export const ${activeExport}\\b`))
    }

    for (const retiredExport of [
      'generateReport',
      'getReportStatus',
      'getReportConversations',
      'chatWithReport',
    ]) {
      assert.doesNotMatch(reportClient, new RegExp(`export const ${retiredExport}\\b`))
    }
  })
})
