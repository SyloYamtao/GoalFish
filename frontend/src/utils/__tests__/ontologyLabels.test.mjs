import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import {
  resolveOntologyEdgeLabel,
  resolveOntologyEntityLabel,
  resolveOntologyLabel,
} from '../ontologyLabels.js'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const repoRoot = path.resolve(__dirname, '../../../..')

const en = JSON.parse(fs.readFileSync(path.join(repoRoot, 'locales/en.json'), 'utf8'))
const zh = JSON.parse(fs.readFileSync(path.join(repoRoot, 'locales/zh.json'), 'utf8'))

describe('ontology label i18n', () => {
  it('uses UI locale labels for standard football ontology entities and relations', () => {
    const t = translator(en)

    assert.equal(resolveOntologyEntityLabel({ name: 'FootballTeam', display_name: '球队' }, t), 'Team')
    assert.equal(resolveOntologyEntityLabel({ name: 'Person', display_name: '个人' }, t), 'Person')
    assert.equal(resolveOntologyEdgeLabel({ name: 'PLAYS_FOR', display_name: '效力于' }, t), 'Plays for')
    assert.equal(resolveOntologyLabel({ name: 'PART_OF_COMPETITION', display_name: '属于赛事' }, t), 'Part of competition')
  })

  it('keeps Chinese labels when the UI locale is Chinese', () => {
    const t = translator(zh)

    assert.equal(resolveOntologyEntityLabel({ name: 'FootballTeam', display_name: 'Team' }, t), '球队')
    assert.equal(resolveOntologyEdgeLabel({ name: 'PLAYS_FOR', display_name: 'Plays for' }, t), '效力于')
  })

  it('falls back to generated display names for custom ontology items', () => {
    const t = translator(en)

    assert.equal(resolveOntologyLabel({ name: 'WeatherCondition', display_name: 'Weather condition' }, t), 'Weather condition')
    assert.equal(resolveOntologyLabel({ name: 'UNKNOWN_RELATION' }, t), 'UNKNOWN_RELATION')
  })
})

function translator(messages) {
  return key => key.split('.').reduce((value, part) => value?.[part], messages) || key
}
