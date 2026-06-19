import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import { buildStep4ReportEvidence, resolveReportProjectId } from '../step4ReportEvidence.js'

describe('step4ReportEvidence', () => {
  it('resolves project id from persisted report evidence after a refresh', () => {
    assert.equal(resolveReportProjectId({ project_id: 'proj_top' }), 'proj_top')
    assert.equal(resolveReportProjectId({
      report_metadata: {
        evidence_package: {
          match: { project_id: 'proj_match' },
        },
      },
    }), 'proj_match')
    assert.equal(resolveReportProjectId({
      report_metadata: {
        evidence_package: {
          step1: {
            project: { project_id: 'proj_step1' },
          },
        },
      },
    }), 'proj_step1')
  })

  it('builds a fan-readable evidence panel from report metadata', () => {
    const panel = buildStep4ReportEvidence({
      reportSnapshot: {
        report_metadata: {
          evidence_package: {
            prediction_config: {
              match_name: '加拿大 vs 波黑',
              home_team: '加拿大',
              away_team: '波黑',
              model_name: 'dixon_coles_decay',
              model_version: 'v2',
              fit_status: 'fitted',
              data_sufficiency: 'sufficient',
            },
            scoreline_summary: {
              most_likely_score: '1-0',
              win_draw_loss_probability: {
                home_win: 0.55,
                draw: 0.25,
                away_win: 0.2,
              },
            },
            scorelines_count: 9,
            match_events_count: 77,
            analyst_notes_count: 4,
            coach_discussions_count: 2,
            budget_credibility: {
              external_sources: {
                intl_results: { row_count: 1600 },
                national_elo: { row_count: 244 },
              },
              player_dataset: {
                teams_count: 48,
                players_count: 1176,
              },
              player_availability: {
                home: { available: 26, total: 26 },
                away: { available: 24, total: 24 },
              },
              ledger: {
                total_calls: 26,
                hard_cap: 20,
                cached: 0,
                failures_count: 3,
              },
            },
          },
        },
      },
      predictionStatus: { counts: { scenario_cases: 9 } },
      reportOutline: { sections: [{ title: '胜平负与比分判断' }] },
      generatedSections: { 1: '## 胜平负与比分判断' },
      workflowSteps: [{ key: 'section-1', noLabel: '01', title: '胜平负与比分判断', status: 'done' }],
      statusText: 'Completed',
    })

    assert.equal(panel.verdict.title, '加拿大 1-0 波黑')
    assert.match(panel.verdict.subtitle, /主胜 55\.0%/)
    assert.equal(panel.modelInputs[0].value, 'dixon_coles_decay v2')
    assert.equal(panel.modelInputs[1].value, '主 26/26 · 客 24/24')
    assert.equal(panel.evidenceStats.find(item => item.label === '比赛事件').value, '77')
    assert.match(panel.credibilityItems[0].detail, /26\/20/)
    assert.match(panel.sectionSteps[0].hint, /比分概率/)
  })

  it('falls back to generated section text when score metadata is absent', () => {
    const panel = buildStep4ReportEvidence({
      reportSnapshot: {
        report_metadata: {
          evidence_package: {
            prediction_config: {
              match_name: '加拿大 vs 波黑',
              home_team: '加拿大',
              away_team: '波黑',
            },
          },
        },
      },
      generatedSections: {
        1: '- 最可能比分：1-0\n- 主胜概率：55.0%\n- 平局概率：25.0%\n- 客胜概率：20.0%',
      },
    })

    assert.equal(panel.verdict.title, '加拿大 1-0 波黑')
    assert.match(panel.verdict.subtitle, /平 25\.0%/)
  })

  it('supports nested prediction report assembler v2 evidence packages', () => {
    const panel = buildStep4ReportEvidence({
      reportSnapshot: {
        report_metadata: {
          evidence_package: {
            match: {
              match_name: '阿根廷 vs 法国',
              home_team: '阿根廷',
              away_team: '法国',
            },
            step1: {
              graph_entities_count: 18,
              graph_relationships_count: 31,
              external_sources: ['international_results', 'national_elo'],
              injury_reports: [{ player: '迪马利亚', status: 'questionable' }],
            },
            step2: {
              prediction_config: {
                model_name: 'dixon_coles_decay',
                model_version: 'v2',
                fit_status: 'fitted',
                data_sufficiency: 'sufficient',
              },
              formations: {
                home: '4-3-3',
                away: '4-2-3-1',
              },
              team_strengths: [
                { team_role: 'home', team_name: '阿根廷', attack_rating: 82, defense_rating: 78, transition_rating: 80, goalkeeper_rating: 77, confidence: 0.74 },
                { team_role: 'away', team_name: '法国', attack_rating: 85, defense_rating: 80, transition_rating: 84, goalkeeper_rating: 81, confidence: 0.76 },
              ],
              team_rankings: {
                home: { fifa_rank: 1, elo_rank: 2 },
                away: { fifa_rank: 2, elo_rank: 1 },
              },
              player_attributes: {
                home: [{ name: '梅西', position: 'RW', overall: 91, attack: 94, passing: 92, availability: 'available' }],
                away: [{ name: '姆巴佩', position: 'LW', overall: 91, attack: 95, pace: 97, availability: 'available' }],
              },
              lineups: {
                home: [{ name: '梅西', position: 'RW' }],
                away: [{ name: '姆巴佩', position: 'LW' }],
              },
              coach_discussions: [
                { topic: '阵型', summary: '阿根廷需要保护肋部空间。', consensus_score: 0.72 },
                { topic: '压迫', summary: '法国会用速度打转换。', consensus_score: 0.68 },
              ],
              player_availability: {
                home: { available: 22, total: 26 },
                away: { available: 23, total: 26 },
              },
            },
            step3: {
              scoreline_summary: {
                most_likely_score: '1-1',
                win_draw_loss_probability: {
                  home_win: 0.34,
                  draw: 0.31,
                  away_win: 0.35,
                },
                top_score_candidates: [
                  { score: '1-1', probability: 0.18 },
                  { score: '1-2', probability: 0.14 },
                ],
              },
              top_scores: [{ score: '1-1', probability: 0.18 }],
              xg: { home: 1.42, away: 1.51 },
              scorelines: [{}, {}, {}],
              scenario_spaces: [
                { space_name: '均势基准', weight: 0.34, summary: '双方机会接近' },
              ],
              scenario_cases: [{}, {}, {}, {}, {}, {}, {}, {}, {}],
              event_timeline: [
                { period: '0-30', trigger: '开局压迫', event: '法国左路推进', score_impact: '提高客队进球概率' },
              ],
              events: [
                { minute: 18, event_type: 'CHANCE_CREATED', event_label: '机会', team: '法国', score: '0-0', description: '法国左路形成射门。' },
                { minute: 52, event_type: 'VAR_CHECK', event_label: 'VAR', team: '阿根廷', score: '1-1', description: '禁区接触需要复核。' },
                {}, {}, {}, {}, {}, {},
              ],
              analyst_notes: [{}, {}, {}],
              uncertainty_factors: ['VAR 改判会改变比分方向'],
            },
            credibility: {
              budget: {
                player_dataset: {
                  teams_count: 48,
                  players_count: 1176,
                },
                ledger: {
                  total_calls: 12,
                  hard_cap: 25,
                  cached: 4,
                  failures: [],
                },
                budget_profile: {
                  profile_key: 'middle',
                },
              },
              data_counts: {
                step1_graph_entities: 18,
                step1_graph_relationships: 31,
                step2_lineup_players: 22,
                step3_scorelines: 3,
                step3_match_events: 8,
              },
              warnings: ['部分伤停需要临场确认'],
            },
          },
        },
      },
      reportOutline: {
        sections: [
          { title: '比赛结论摘要' },
          { title: '双方基本面与图谱证据' },
          { title: '战术、阵型与预计首发' },
        ],
      },
    })

    assert.equal(panel.verdict.title, '阿根廷 1-1 法国')
    assert.match(panel.verdict.subtitle, /客胜 35\.0%/)
    assert.equal(panel.modelInputs[1].value, '主 22/26 · 客 23/26')
    assert.equal(panel.modelInputs.find(item => item.label === '外部源').value, '2 组')
    assert.equal(panel.evidenceStats.find(item => item.label === '比赛事件').value, '8')
    assert.equal(panel.evidenceStats.find(item => item.label === '教练讨论').value, '2')
    assert.match(panel.credibilityItems[0].detail, /12\/25/)
    assert.match(panel.sectionSteps[1].hint, /伤停/)
    assert.match(panel.sectionSteps[2].hint, /预计首发/)
    assert.deepEqual(panel.insightTabs.map(tab => tab.key), ['overview', 'scores', 'lineups', 'events', 'risks'])
    assert.equal(panel.probabilityBars.find(item => item.key === 'home_win').percentLabel, '34.0%')
    assert.equal(panel.teamComparison.find(item => item.key === 'home').formation, '4-3-3')
    assert.equal(panel.teamComparison.find(item => item.key === 'away').xg, '1.51')
    assert.equal(panel.scoreCandidates[0].score, '1-1')
    assert.equal(panel.keyPlayers[0].name, '梅西')
    assert.equal(panel.coachNotes[0].topic, '阵型')
    assert.equal(panel.scenarioHighlights[0].name, '均势基准')
    assert.equal(panel.eventTimeline[0].period, '0-30')
    assert.equal(panel.eventItems[1].label, 'VAR')
    assert.equal(panel.riskItems.find(item => item.key === 'cards').tone, 'warn')
    assert.match(panel.sourceHighlights.find(item => item.label === '图谱').value, /18 实体/)
  })

  it('exposes lineup, tactics, and matchup widgets from report metadata', () => {
    const panel = buildStep4ReportEvidence({
      reportSnapshot: {
        report_metadata: {
          widgets: {
            lineup_widget: {
              home: {
                team: '葡萄牙',
                formation: '4-2-3-1',
                confidence: 0.72,
                players: [{ name: 'Fernandes', number: 8, position: 'CM', overall: 84, pitch_slot: 'LCM' }],
                bench: [],
              },
              away: {
                team: '刚果（金）',
                formation: '4-3-3',
                confidence: 0.64,
                players: [{ name: 'Bakambu', number: 17, position: 'ST', overall: 76, pitch_slot: 'ST' }],
                bench: [],
              },
            },
            tactics_widget: {
              home: { coach: '资料未明确', attacking_plan: '中路组织', defensive_plan: '压缩中路' },
              away: { coach: '资料未明确', attacking_plan: '边路反击', defensive_plan: '低位保护' },
            },
            matchup_widget: [
              { zone: '中路', home_player: 'Fernandes', away_player: 'Bakambu', why_it_matters: '决定推进质量', advantage: 'home' },
            ],
          },
          evidence_package: {},
        },
      },
    })

    assert.equal(panel.widgets.lineup.home.team, '葡萄牙')
    assert.equal(panel.widgets.lineup.away.formation, '4-3-3')
    assert.equal(panel.widgets.tactics.home.attacking_plan, '中路组织')
    assert.equal(panel.widgets.matchups[0].zone, '中路')
    assert.equal(panel.insightTabs.find(tab => tab.key === 'lineups').meta, '2人')
  })
})
