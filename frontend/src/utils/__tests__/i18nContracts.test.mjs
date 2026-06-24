import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const repoRoot = path.resolve(__dirname, '../../../..')

const readJson = relativePath => JSON.parse(fs.readFileSync(path.join(repoRoot, relativePath), 'utf8'))

describe('i18n contracts', () => {
  it('defaults the frontend locale to English and only respects saved zh/en', () => {
    const source = fs.readFileSync(path.join(repoRoot, 'frontend/src/i18n/index.js'), 'utf8')

    assert.match(source, /initialLocale\s*=.*\?\s*savedLocale\s*:\s*'en'/s)
    assert.match(source, /fallbackLocale:\s*'en'/)
    assert.doesNotMatch(source, /localStorage\.getItem\('locale'\)\s*\|\|\s*'zh'/)
  })

  it('limits the language switcher registry to Chinese and English', () => {
    const languages = readJson('locales/languages.json')
    assert.deepEqual(Object.keys(languages).sort(), ['en', 'zh'])
    assert.equal(languages.en.label, 'English')
    assert.equal(languages.zh.label, '中文')
  })

  it('keeps key frontend UI modules wired to i18n instead of hardcoded Chinese text', () => {
    const strictFiles = [
      'frontend/src/i18n/index.js',
      'frontend/src/components/LanguageSwitcher.vue',
      'frontend/src/components/Step1GraphBuild.vue',
      'frontend/src/components/Step2EnvSetup.vue',
      'frontend/src/components/Step3Simulation.vue',
      'frontend/src/components/GraphPanel.vue',
      'frontend/src/components/HistoryDatabase.vue',
      'frontend/src/components/prediction/DataSourcesCard.vue',
      'frontend/src/components/prediction/DatasetPickerModal.vue',
      'frontend/src/components/prediction/EvidenceChip.vue',
      'frontend/src/components/prediction/InfoTooltip.vue',
      'frontend/src/components/prediction/KeyMatchups.vue',
      'frontend/src/components/prediction/LLMBudgetCustomPanel.vue',
      'frontend/src/components/prediction/LLMBudgetMeter.vue',
      'frontend/src/components/prediction/LLMBudgetSelector.vue',
      'frontend/src/components/prediction/LineupPitch.vue',
      'frontend/src/components/prediction/MatchEventRow.vue',
      'frontend/src/components/prediction/ModalTrajectoryFootnote.vue',
      'frontend/src/components/prediction/PlayerRosterDrawer.vue',
      'frontend/src/components/prediction/RosterSummaryCard.vue',
      'frontend/src/components/prediction/TacticsPanel.vue',
      'frontend/src/utils/evidenceSourceLabels.js',
      'frontend/src/utils/ontologyLabels.js',
      'frontend/src/utils/step2TeamStrength.js',
      'frontend/src/utils/step3Adapters.js',
      'frontend/src/utils/workflowRegenerate.js',
    ]

    const offenders = []
    for (const file of strictFiles) {
      const source = stripNonUiSource(fs.readFileSync(path.join(repoRoot, file), 'utf8'))
      source.split('\n').forEach((line, index) => {
        if (/[\u4e00-\u9fff]/.test(line)) {
          offenders.push(`${file}:${index + 1}: ${line.trim()}`)
        }
      })
    }

    assert.deepEqual(offenders, [])
  })

  it('only leaves Chinese text in report parsers for legacy generated-content matching', () => {
    const parserFiles = [
      'frontend/src/components/Step4Report.vue',
      'frontend/src/components/Step5Interaction.vue',
      'frontend/src/utils/step4ReportEvidence.js',
    ]

    const offenders = []
    for (const file of parserFiles) {
      const source = stripNonUiSource(fs.readFileSync(path.join(repoRoot, file), 'utf8'))
      source.split('\n').forEach((line, index) => {
        if (/[\u4e00-\u9fff]/.test(line) && !isAllowedParserChinese(line)) {
          offenders.push(`${file}:${index + 1}: ${line.trim()}`)
        }
      })
    }

    assert.deepEqual(offenders, [])
  })

  it('keeps the visible language selector labels limited to Chinese and English', () => {
    const languages = readJson('locales/languages.json')
    const labels = Object.values(languages).map(item => item.label).sort()
    assert.deepEqual(labels, ['English', '中文'])
  })
})

function stripNonUiSource(source) {
  return source
    .replace(/<style[\s\S]*?<\/style>/g, '')
    .replace(/<!--[\s\S]*?-->/g, '')
    .replace(/\/\/.*$/gm, '')
    .replace(/\/\*[\s\S]*?\*\//g, '')
}

function isAllowedParserChinese(line) {
  const trimmed = line.trim()
  if (/\/.*[\u4e00-\u9fff].*\//.test(trimmed)) return true
  if (/未获得回复|无回复/.test(trimmed) && /includes/.test(trimmed)) return true
  if (/错误|警告/.test(trimmed) && /log\.includes/.test(trimmed)) return true
  return false
}
