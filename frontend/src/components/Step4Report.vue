<template>
  <div class="report-panel">
    <!-- Main Split Layout -->
    <div class="main-split-layout">
      <!-- LEFT PANEL: Report Style -->
      <div class="left-panel report-style" ref="leftPanel">
        <div v-if="reportOutline" class="report-content-wrapper">
          <!-- Report Header -->
          <div class="report-header-block">
            <div class="report-meta">
              <span class="report-tag">Prediction Report</span>
              <span class="report-id">ID: {{ reportId || 'REF-2024-X92' }}</span>
            </div>
            <h1 class="main-title">{{ reportOutline.title }}</h1>
            <p class="sub-title">{{ reportOutline.summary }}</p>
            <div class="header-divider"></div>
          </div>

          <!-- Sections List -->
          <div class="sections-list">
            <div 
              v-for="(section, idx) in reportOutline.sections" 
              :key="idx"
              class="report-section-item"
              :class="{ 
                'is-active': currentSectionIndex === idx + 1,
                'is-completed': isSectionCompleted(idx + 1),
                'is-pending': !isSectionCompleted(idx + 1) && currentSectionIndex !== idx + 1
              }"
            >
              <div class="section-header-row" @click="toggleSectionCollapse(idx)" :class="{ 'clickable': isSectionCompleted(idx + 1) }">
                <span class="section-number">{{ String(idx + 1).padStart(2, '0') }}</span>
                <h3 class="section-title">{{ section.title }}</h3>
                <svg 
                  v-if="isSectionCompleted(idx + 1)" 
                  class="collapse-icon" 
                  :class="{ 'is-collapsed': collapsedSections.has(idx) }"
                  viewBox="0 0 24 24" 
                  width="20" 
                  height="20" 
                  fill="none" 
                  stroke="currentColor" 
                  stroke-width="2"
                >
                  <polyline points="6 9 12 15 18 9"></polyline>
                </svg>
              </div>
              
              <div class="section-body" v-show="!collapsedSections.has(idx)">
                <!-- Completed Content -->
                <div v-if="generatedSections[idx + 1]">
                  <div v-if="isTacticsSection(section)" class="structured-report-widgets">
                    <LineupPitch
                      v-if="hasLineupWidget"
                      :home="evidencePanel.widgets.lineup.home"
                      :away="evidencePanel.widgets.lineup.away"
                    />
                    <div v-else class="lineup-widget-empty">暂无可渲染的预计首发阵型图</div>
                    <TacticsPanel
                      :home-team="evidencePanel.widgets.lineup.home?.team || evidencePanel.verdict.eyebrow"
                      :away-team="evidencePanel.widgets.lineup.away?.team || ''"
                      :tactics="evidencePanel.widgets.tactics"
                    />
                    <KeyMatchups :matchups="evidencePanel.widgets.matchups" />
                  </div>
                  <div class="generated-content" v-html="renderMarkdown(generatedSections[idx + 1])"></div>
                </div>
                
                <!-- Loading State -->
                <div v-else-if="currentSectionIndex === idx + 1" class="loading-state">
                  <div class="loading-icon">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                      <circle cx="12" cy="12" r="10" stroke-width="4" stroke="#E5E7EB"></circle>
                      <path d="M12 2a10 10 0 0 1 10 10" stroke-width="4" stroke="#4B5563" stroke-linecap="round"></path>
                    </svg>
                  </div>
                  <span class="loading-text">{{ $t('step4.generatingSection', { title: section.title }) }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- Waiting State -->
        <div v-if="!reportOutline && isFailed" class="waiting-placeholder">
          <div class="waiting-animation">
            <div class="waiting-ring"></div>
            <div class="waiting-ring"></div>
            <div class="waiting-ring"></div>
          </div>
          <span class="waiting-text">Report generation failed.</span>
        </div>

        <div v-else-if="!reportOutline" class="waiting-placeholder">
          <div class="waiting-animation">
            <div class="waiting-ring"></div>
            <div class="waiting-ring"></div>
            <div class="waiting-ring"></div>
          </div>
          <span class="waiting-text">Waiting for prediction report...</span>
        </div>
      </div>

      <!-- RIGHT PANEL: Workflow Timeline -->
      <div class="right-panel" ref="rightPanel">
        <div class="panel-header" :class="`panel-header--${activeStep.status}`" v-if="!isComplete">
          <span class="header-dot" v-if="activeStep.status === 'active'"></span>
          <span class="header-index mono">{{ activeStep.noLabel }}</span>
          <span class="header-title">{{ activeStep.title }}</span>
          <span class="header-meta mono" v-if="activeStep.meta">{{ activeStep.meta }}</span>
        </div>

        <!-- Report Evidence Overview -->
        <div class="workflow-overview evidence-overview" v-if="agentLogs.length > 0 || reportOutline">
          <div class="evidence-status-row">
            <div class="evidence-kicker">
              <span class="metric-label">Report Context</span>
              <span class="metric-pill" :class="`pill--${statusClass}`">{{ statusText }}</span>
            </div>
            <span class="metric-value mono">{{ completedSections }}/{{ totalSections }} sections</span>
          </div>

          <div class="match-verdict">
            <span class="match-eyebrow">{{ evidencePanel.verdict.eyebrow }}</span>
            <strong>{{ evidencePanel.verdict.title }}</strong>
            <span>{{ evidencePanel.verdict.subtitle }}</span>
          </div>

          <div v-if="isHistoricalReport" class="historical-report-notice">
            当前查看的是历史报告，已不属于项目当前活跃流程。可以回看内容，继续问答前请重新生成 Step4。
          </div>

          <div class="evidence-grid">
            <div
              v-for="item in evidencePanel.modelInputs"
              :key="item.label"
              class="evidence-cell"
            >
              <span>{{ item.label }}</span>
              <strong>{{ item.value }}</strong>
            </div>
          </div>

          <div class="evidence-stats">
            <div
              v-for="item in evidencePanel.evidenceStats"
              :key="item.label"
              class="evidence-stat"
            >
              <strong class="mono">{{ item.value }}</strong>
              <span>{{ item.label }}</span>
            </div>
          </div>

          <div class="credibility-strip">
            <div
              v-for="item in evidencePanel.credibilityItems"
              :key="item.label"
              class="credibility-item"
              :class="`credibility-item--${item.tone}`"
            >
              <span>{{ item.label }}</span>
              <strong>{{ item.detail }}</strong>
            </div>
          </div>

          <div class="evidence-tabs" role="tablist" aria-label="Step4 evidence dashboard">
            <button
              v-for="tab in evidencePanel.insightTabs"
              :key="tab.key"
              type="button"
              class="evidence-tab"
              :class="{ 'is-active': activeEvidenceTab === tab.key }"
              role="tab"
              :aria-selected="activeEvidenceTab === tab.key"
              @click="setEvidenceTab(tab.key)"
            >
              <span>{{ tab.label }}</span>
              <small>{{ tab.meta }}</small>
            </button>
          </div>

          <div class="evidence-insight-panel">
            <template v-if="activeEvidenceTab === 'overview'">
              <div class="insight-section">
                <div class="insight-section-title">胜平负概率</div>
                <div class="probability-list">
                  <div
                    v-for="item in evidencePanel.probabilityBars"
                    :key="item.key"
                    class="probability-row"
                  >
                    <div class="probability-label">
                      <span>{{ item.label }}</span>
                      <strong>{{ item.team }}</strong>
                    </div>
                    <div class="probability-track" :aria-label="`${item.label} ${item.percentLabel}`">
                      <span class="probability-fill" :style="{ width: `${item.pct}%` }"></span>
                    </div>
                    <span class="probability-value mono">{{ item.bar }}</span>
                    <span class="probability-percent mono">{{ item.percentLabel }}</span>
                  </div>
                </div>
              </div>

              <div class="insight-section">
                <div class="insight-section-title">证据来源</div>
                <div class="source-mini-grid">
                  <div
                    v-for="item in evidencePanel.sourceHighlights"
                    :key="item.label"
                    class="source-mini-cell"
                  >
                    <span>{{ item.detail }}</span>
                    <strong>{{ item.value }}</strong>
                    <small>{{ item.label }}</small>
                  </div>
                </div>
              </div>

              <div class="insight-section">
                <div class="insight-section-title">球队快照</div>
                <div class="team-compare-list">
                  <div
                    v-for="team in evidencePanel.teamComparison"
                    :key="team.key"
                    class="team-compare-row"
                  >
                    <div class="team-compare-head">
                      <strong>{{ team.team }}</strong>
                      <span>{{ team.formation }}</span>
                    </div>
                    <div class="team-compare-metrics">
                      <span>攻 {{ team.attack }}</span>
                      <span>防 {{ team.defense }}</span>
                      <span>xG {{ team.xg }}</span>
                      <span>可用 {{ team.availability }}</span>
                    </div>
                    <small>{{ team.ranking }}</small>
                  </div>
                </div>
              </div>
            </template>

            <template v-else-if="activeEvidenceTab === 'scores'">
              <div class="insight-section">
                <div class="insight-section-title">Top 比分候选</div>
                <button
                  v-for="item in evidencePanel.scoreCandidates"
                  :key="item.key"
                  type="button"
                  class="score-candidate"
                  @click="jumpToReportSectionByTitle('胜平负与比分预测')"
                >
                  <span class="score-rank mono">{{ String(item.rank).padStart(2, '0') }}</span>
                  <strong>{{ item.score }}</strong>
                  <span class="score-context">{{ item.context }}</span>
                  <span class="score-prob mono">{{ item.probability }}</span>
                </button>
                <div v-if="!evidencePanel.scoreCandidates.length" class="insight-empty">资料未明确</div>
              </div>

              <div class="insight-section">
                <div class="insight-section-title">场景权重</div>
                <button
                  v-for="item in evidencePanel.scenarioHighlights"
                  :key="item.key"
                  type="button"
                  class="scenario-row"
                  @click="jumpToReportSectionByTitle('胜平负与比分预测')"
                >
                  <strong>{{ item.name }}</strong>
                  <span>{{ item.summary }}</span>
                  <small class="mono">{{ item.weight }}</small>
                </button>
                <div v-if="!evidencePanel.scenarioHighlights.length" class="insight-empty">资料未明确</div>
              </div>
            </template>

            <template v-else-if="activeEvidenceTab === 'lineups'">
              <div class="insight-section" v-if="hasLineupWidget">
                <div class="insight-section-title">阵型图</div>
                <button
                  type="button"
                  class="lineup-widget-jump"
                  @click="jumpToReportSectionByTitle('战术、阵型与预计首发')"
                >
                  <strong>{{ evidencePanel.widgets.lineup.home?.team || '主队' }} {{ evidencePanel.widgets.lineup.home?.formation || '-' }}</strong>
                  <span>vs</span>
                  <strong>{{ evidencePanel.widgets.lineup.away?.formation || '-' }} {{ evidencePanel.widgets.lineup.away?.team || '客队' }}</strong>
                  <small>点击查看双方阵型球场图</small>
                </button>
              </div>

              <div class="insight-section">
                <div class="insight-section-title">球队强度对比</div>
                <div class="team-compare-list">
                  <button
                    v-for="team in evidencePanel.teamComparison"
                    :key="team.key"
                    type="button"
                    class="team-compare-row is-clickable"
                    @click="jumpToReportSectionByTitle('战术、阵型与预计首发')"
                  >
                    <div class="team-compare-head">
                      <strong>{{ team.team }}</strong>
                      <span>{{ team.formation }}</span>
                    </div>
                    <div class="team-compare-metrics">
                      <span>攻 {{ team.attack }}</span>
                      <span>防 {{ team.defense }}</span>
                      <span>转换 {{ team.transition }}</span>
                      <span>门将 {{ team.goalkeeper }}</span>
                    </div>
                    <small>可用 {{ team.availability }} · 可信 {{ team.confidence }}</small>
                  </button>
                </div>
              </div>

              <div class="insight-section">
                <div class="insight-section-title">关键球员</div>
                <button
                  v-for="player in evidencePanel.keyPlayers"
                  :key="player.key"
                  type="button"
                  class="player-row"
                  @click="jumpToReportSectionByTitle('战术、阵型与预计首发')"
                >
                  <span>{{ player.team }}</span>
                  <strong>{{ player.name }}</strong>
                  <small>{{ player.position }} · {{ player.tag }} · {{ player.availability }}</small>
                </button>
                <div v-if="!evidencePanel.keyPlayers.length" class="insight-empty">资料未明确</div>
              </div>

              <div class="insight-section" v-if="evidencePanel.coachNotes.length">
                <div class="insight-section-title">教练讨论</div>
                <button
                  v-for="note in evidencePanel.coachNotes"
                  :key="note.key"
                  type="button"
                  class="coach-note-row"
                  @click="jumpToReportSectionByTitle('战术、阵型与预计首发')"
                >
                  <strong>{{ note.topic }}</strong>
                  <span>{{ note.summary }}</span>
                  <small>共识 {{ note.consensus }}</small>
                </button>
              </div>

              <div class="insight-section" v-if="evidencePanel.widgets.matchups.length">
                <div class="insight-section-title">关键对位</div>
                <button
                  v-for="item in evidencePanel.widgets.matchups.slice(0, 3)"
                  :key="`${item.zone}-${item.home_player}-${item.away_player}`"
                  type="button"
                  class="coach-note-row"
                  @click="jumpToReportSectionByTitle('战术、阵型与预计首发')"
                >
                  <strong>{{ item.zone || '区域' }}：{{ item.home_player || '主队球员' }} vs {{ item.away_player || '客队球员' }}</strong>
                  <span>{{ item.why_it_matters || '资料未明确' }}</span>
                  <small>{{ item.advantage === 'home' ? '主队占优' : item.advantage === 'away' ? '客队占优' : '接近' }}</small>
                </button>
              </div>
            </template>

            <template v-else-if="activeEvidenceTab === 'events'">
              <div class="insight-section">
                <div class="insight-section-title">比赛时间线</div>
                <button
                  v-for="item in evidencePanel.eventTimeline"
                  :key="item.key"
                  type="button"
                  class="event-bucket"
                  @click="jumpToReportSectionByTitle('关键比赛事件剧本')"
                >
                  <strong class="mono">{{ item.period }}</strong>
                  <span>{{ item.event }}</span>
                  <small>{{ item.scoreImpact }}</small>
                </button>
              </div>

              <div class="insight-section">
                <div class="insight-section-title">事件链样本</div>
                <button
                  v-for="item in evidencePanel.eventItems"
                  :key="item.key"
                  type="button"
                  class="event-item"
                  @click="jumpToReportSectionByTitle('关键比赛事件剧本')"
                >
                  <span class="mono">{{ item.minute }}</span>
                  <strong>{{ item.label }}</strong>
                  <small>{{ item.team }} · {{ item.score }}</small>
                  <em>{{ item.description }}</em>
                </button>
                <div v-if="!evidencePanel.eventItems.length" class="insight-empty">资料未明确</div>
              </div>
            </template>

            <template v-else-if="activeEvidenceTab === 'risks'">
              <div class="insight-section">
                <div class="insight-section-title">风险与可信度</div>
                <button
                  v-for="item in evidencePanel.riskItems"
                  :key="item.key"
                  type="button"
                  class="risk-row"
                  :class="`risk-row--${item.tone}`"
                  @click="jumpToReportSectionByTitle('风险、不确定性与可信度说明')"
                >
                  <span>{{ item.label }}</span>
                  <strong>{{ item.signal }}</strong>
                  <small>{{ item.impact }}</small>
                </button>
              </div>
            </template>
          </div>

          <div class="workflow-steps evidence-steps" v-if="evidencePanel.sectionSteps.length > 0">
            <div
              v-for="(step, sidx) in evidencePanel.sectionSteps"
              :key="step.key"
              class="wf-step"
              :class="`wf-step--${step.status}`"
              role="button"
              tabindex="0"
              @click="jumpToReportSection(step, sidx)"
              @keydown.enter.prevent="jumpToReportSection(step, sidx)"
              @keydown.space.prevent="jumpToReportSection(step, sidx)"
            >
              <div class="wf-step-connector">
                <div class="wf-step-dot"></div>
                <div class="wf-step-line" v-if="sidx < evidencePanel.sectionSteps.length - 1"></div>
              </div>

              <div class="wf-step-content">
                <div class="wf-step-title-row">
                  <span class="wf-step-index mono">{{ step.noLabel }}</span>
                  <span class="wf-step-title">{{ step.title }}</span>
                  <span class="wf-step-meta mono" v-if="step.meta">{{ step.meta }}</span>
                </div>
                <div class="wf-step-hint">{{ step.hint }}</div>
              </div>
            </div>
          </div>

          <!-- Step navigation -->
          <div v-if="simulationId || isComplete" class="step-nav-actions">
            <button v-if="simulationId" class="next-step-btn secondary-step-btn" @click="goToSimulation">
              <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="19" y1="12" x2="5" y2="12"></line>
                <polyline points="12 19 5 12 12 5"></polyline>
              </svg>
              <span>{{ $t('step4.backToSimulation') }}</span>
            </button>
            <button
              v-if="isComplete && activeProjectId"
              class="next-step-btn secondary-step-btn"
              type="button"
              :disabled="isRegeneratingReport"
              @click="regenerateStep4Report"
            >
              <span>{{ isRegeneratingReport ? '重新生成中...' : '重新生成报告' }}</span>
            </button>
            <button v-if="isComplete && !isHistoricalReport" class="next-step-btn" @click="goToInteraction">
              <span>{{ $t('step4.goToInteraction') }}</span>
              <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="5" y1="12" x2="19" y2="12"></line>
                <polyline points="12 5 19 12 12 19"></polyline>
              </svg>
            </button>
          </div>

          <div class="workflow-divider"></div>
        </div>

        <div class="workflow-timeline">
          <TransitionGroup name="timeline-item">
            <div 
              v-for="(log, idx) in displayLogs" 
              :key="log.timestamp + '-' + idx"
              class="timeline-item"
              :class="getTimelineItemClass(log, idx, displayLogs.length)"
            >
              <!-- Timeline Connector -->
              <div class="timeline-connector">
                <div class="connector-dot" :class="getConnectorClass(log, idx, displayLogs.length)"></div>
                <div class="connector-line" v-if="idx < displayLogs.length - 1"></div>
              </div>
              
              <!-- Timeline Content -->
              <div class="timeline-content">
                <div class="timeline-header">
                  <span class="action-label">{{ getActionLabel(log.action) }}</span>
                  <span class="action-time">{{ formatTime(log.timestamp) }}</span>
                </div>
                
                <!-- Action Body - Different for each type -->
                <div class="timeline-body" :class="{ 'collapsed': isLogCollapsed(log) }" @click="toggleLogExpand(log)">
                  
                  <!-- Report Start -->
                  <template v-if="log.action === 'report_start'">
                    <div class="info-row">
                      <span class="info-key">{{ isFootballPredictionMode ? 'Prediction Run' : 'Simulation' }}</span>
                      <span class="info-val mono">{{ log.details?.simulation_id }}</span>
                    </div>
                    <div class="info-row" v-if="log.details?.simulation_requirement">
                      <span class="info-key">Requirement</span>
                      <span class="info-val">{{ log.details.simulation_requirement }}</span>
                    </div>
                  </template>

                  <!-- Planning -->
                  <template v-if="log.action === 'planning_start'">
                    <div class="status-message planning">{{ log.details?.message }}</div>
                  </template>
                  <template v-if="log.action === 'planning_complete'">
                    <div class="status-message success">{{ log.details?.message }}</div>
                    <div class="outline-badge" v-if="log.details?.outline">
                      {{ log.details.outline.sections?.length || 0 }} sections planned
                    </div>
                  </template>

                  <!-- Section Start -->
                  <template v-if="log.action === 'section_start'">
                    <div class="section-tag">
                      <span class="tag-num">#{{ log.section_index }}</span>
                      <span class="tag-title">{{ log.section_title }}</span>
                    </div>
                  </template>
                  
                  <!-- Section Content Generated (内容生成完成，但整个章节可能还没完成) -->
                  <template v-if="log.action === 'section_content'">
                    <div class="section-tag content-ready">
                      <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M12 20h9"></path>
                        <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"></path>
                      </svg>
                      <span class="tag-title">{{ log.section_title }}</span>
                    </div>
                  </template>

                  <!-- Section Complete (章节生成完成) -->
                  <template v-if="log.action === 'section_complete'">
                    <div class="section-tag completed">
                      <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                        <polyline points="20 6 9 17 4 12"></polyline>
                      </svg>
                      <span class="tag-title">{{ log.section_title }}</span>
                    </div>
                  </template>

                  <!-- Tool Call -->
                  <template v-if="log.action === 'tool_call'">
                    <div class="tool-badge" :class="'tool-' + getToolColor(log.details?.tool_name)">
                      <!-- Deep Insight - Lightbulb -->
                      <svg v-if="getToolIcon(log.details?.tool_name) === 'lightbulb'" class="tool-icon" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M9 18h6M10 22h4M12 2a7 7 0 0 0-4 12.5V17a1 1 0 0 0 1 1h6a1 1 0 0 0 1-1v-2.5A7 7 0 0 0 12 2z"></path>
                      </svg>
                      <!-- Panorama Search - Globe -->
                      <svg v-else-if="getToolIcon(log.details?.tool_name) === 'globe'" class="tool-icon" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                        <circle cx="12" cy="12" r="10"></circle>
                        <path d="M2 12h20M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path>
                      </svg>
                      <!-- Analyst Review - Users -->
                      <svg v-else-if="getToolIcon(log.details?.tool_name) === 'users'" class="tool-icon" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path>
                        <circle cx="9" cy="7" r="4"></circle>
                        <path d="M23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"></path>
                      </svg>
                      <!-- Quick Search - Zap -->
                      <svg v-else-if="getToolIcon(log.details?.tool_name) === 'zap'" class="tool-icon" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                        <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon>
                      </svg>
                      <!-- Graph Stats - Chart -->
                      <svg v-else-if="getToolIcon(log.details?.tool_name) === 'chart'" class="tool-icon" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                        <line x1="18" y1="20" x2="18" y2="10"></line>
                        <line x1="12" y1="20" x2="12" y2="4"></line>
                        <line x1="6" y1="20" x2="6" y2="14"></line>
                      </svg>
                      <!-- Entity Query - Database -->
                      <svg v-else-if="getToolIcon(log.details?.tool_name) === 'database'" class="tool-icon" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                        <ellipse cx="12" cy="5" rx="9" ry="3"></ellipse>
                        <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"></path>
                        <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"></path>
                      </svg>
                      <!-- Default - Tool -->
                      <svg v-else class="tool-icon" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"></path>
                      </svg>
                      {{ getToolDisplayName(log.details?.tool_name) }}
                    </div>
                    <div v-if="log.details?.parameters && expandedLogs.has(log.timestamp)" class="tool-params">
                      <pre>{{ formatParams(log.details.parameters) }}</pre>
                    </div>
                  </template>

                  <!-- Tool Result -->
                  <template v-if="log.action === 'tool_result'">
                    <div class="result-wrapper" :class="'result-' + log.details?.tool_name">
                      <!-- Hide result-meta for tools that show stats in their own header -->
                      <div v-if="!['interview_agents', 'insight_forge', 'panorama_search', 'quick_search'].includes(log.details?.tool_name)" class="result-meta">
                        <span class="result-tool">{{ getToolDisplayName(log.details?.tool_name) }}</span>
                        <span class="result-size">{{ formatResultSize(log.details?.result_length) }}</span>
                      </div>
                      
                      <!-- Structured Result Display -->
                      <div v-if="!showRawResult[log.timestamp]" class="result-structured">
                        <!-- Interview Agents - Special Display -->
                        <template v-if="log.details?.tool_name === 'interview_agents'">
                          <InterviewDisplay :result="parseInterview(log.details.result)" :result-length="log.details?.result_length" />
                        </template>
                        
                        <!-- Insight Forge -->
                        <template v-else-if="log.details?.tool_name === 'insight_forge'">
                          <InsightDisplay :result="parseInsightForge(log.details.result)" :result-length="log.details?.result_length" />
                        </template>
                        
                        <!-- Panorama Search -->
                        <template v-else-if="log.details?.tool_name === 'panorama_search'">
                          <PanoramaDisplay :result="parsePanorama(log.details.result)" :result-length="log.details?.result_length" />
                        </template>
                        
                        <!-- Quick Search -->
                        <template v-else-if="log.details?.tool_name === 'quick_search'">
                          <QuickSearchDisplay :result="parseQuickSearch(log.details.result)" :result-length="log.details?.result_length" />
                        </template>
                        
                        <!-- Default -->
                        <template v-else>
                          <pre class="raw-preview">{{ truncateText(log.details?.result, 300) }}</pre>
                        </template>
                      </div>
                      
                      <!-- Raw Result -->
                      <div v-else class="result-raw">
                        <pre>{{ log.details?.result }}</pre>
                      </div>
                    </div>
                  </template>

                  <!-- LLM Response -->
                  <template v-if="log.action === 'llm_response'">
                    <div class="llm-meta">
                      <span class="meta-tag">Iteration {{ log.details?.iteration }}</span>
                      <span class="meta-tag" :class="{ active: log.details?.has_tool_calls }">
                        Tools: {{ log.details?.has_tool_calls ? 'Yes' : 'No' }}
                      </span>
                      <span class="meta-tag" :class="{ active: log.details?.has_final_answer, 'final-answer': log.details?.has_final_answer }">
                        Final: {{ log.details?.has_final_answer ? 'Yes' : 'No' }}
                      </span>
                    </div>
                    <!-- 当是最终答案时，显示特殊提示 -->
                    <div v-if="log.details?.has_final_answer" class="final-answer-hint">
                      <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                        <polyline points="20 6 9 17 4 12"></polyline>
                      </svg>
                      <span>Section "{{ log.section_title }}" content generated</span>
                    </div>
                    <div v-if="expandedLogs.has(log.timestamp) && log.details?.response" class="llm-content">
                      <pre>{{ log.details.response }}</pre>
                    </div>
                  </template>

                  <!-- Report Complete -->
                  <template v-if="log.action === 'report_complete'">
                    <div class="complete-banner">
                      <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path>
                        <polyline points="22 4 12 14.01 9 11.01"></polyline>
                      </svg>
                      <span>Report Generation Complete</span>
                    </div>
                  </template>
                </div>

                <!-- Footer: Elapsed Time + Action Buttons -->
                <div class="timeline-footer" v-if="log.elapsed_seconds || (log.action === 'tool_call' && log.details?.parameters) || log.action === 'tool_result' || (log.action === 'llm_response' && log.details?.response)">
                  <span v-if="log.elapsed_seconds" class="elapsed-badge">+{{ log.elapsed_seconds.toFixed(1) }}s</span>
                  <span v-else class="elapsed-placeholder"></span>
                  
                  <div class="footer-actions">
                    <!-- Tool Call: Show/Hide Params -->
                    <button v-if="log.action === 'tool_call' && log.details?.parameters" class="action-btn" @click.stop="toggleLogExpand(log)">
                      {{ expandedLogs.has(log.timestamp) ? 'Hide Params' : 'Show Params' }}
                    </button>
                    
                    <!-- Tool Result: Raw/Structured View -->
                    <button v-if="log.action === 'tool_result'" class="action-btn" @click.stop="toggleRawResult(log.timestamp, $event)">
                      {{ showRawResult[log.timestamp] ? 'Structured View' : 'Raw Output' }}
                    </button>
                    
                    <!-- LLM Response: Show/Hide Response -->
                    <button v-if="log.action === 'llm_response' && log.details?.response" class="action-btn" @click.stop="toggleLogExpand(log)">
                      {{ expandedLogs.has(log.timestamp) ? 'Hide Response' : 'Show Response' }}
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </TransitionGroup>

          <!-- Empty State -->
          <div v-if="agentLogs.length === 0 && !isComplete" class="workflow-empty">
            <div class="empty-pulse"></div>
            <span>Waiting for prediction report activity...</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Bottom Console Logs -->
    <div class="console-logs">
      <div class="log-header">
        <span class="log-title">CONSOLE OUTPUT</span>
        <span class="log-id">{{ reportId || 'NO_REPORT' }}</span>
      </div>
      <div class="log-content" ref="logContent">
        <div class="log-line" v-for="(log, idx) in consoleLogs" :key="idx">
          <span class="log-msg" :class="getLogLevelClass(log)">{{ log }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted, nextTick, h, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { getAgentLog, getConsoleLog, getReport, getReportSections } from '../api/report'
import { createPredictionReportForProject, getPredictionStatus } from '../api/prediction'
import { renderMarkdown as renderMarkdownHtml } from '../utils/markdownRenderer'
import { buildStep4ReportEvidence, resolveReportProjectId } from '../utils/step4ReportEvidence'
import { regenerateStepWithConfirm } from '../utils/workflowRegenerate.js'
import LineupPitch from './prediction/LineupPitch.vue'
import TacticsPanel from './prediction/TacticsPanel.vue'
import KeyMatchups from './prediction/KeyMatchups.vue'

const router = useRouter()
const { t } = useI18n()

const props = defineProps({
  reportId: String,
  simulationId: String,
  predictionRunId: String,
  predictionConfigId: String,
  projectId: String,
  isFootballPrediction: Boolean,
  systemLogs: Array
})

const emit = defineEmits(['add-log', 'update-status'])

// Navigation
const goToInteraction = () => {
  if (props.reportId) {
    router.push({ name: 'Interaction', params: { reportId: props.reportId } })
  }
}

const goToSimulation = () => {
  const runId = activePredictionRunId.value
  const query = activePredictionConfigId.value
    ? { prediction_config_id: activePredictionConfigId.value }
    : {}

  if (props.isFootballPrediction && activeProjectId.value && runId) {
    router.push({
      name: 'SimulationRun',
      params: {
        projectId: activeProjectId.value,
        predictionRunId: runId
      },
      query
    })
  } else if (props.simulationId) {
    router.push({
      name: 'SimulationRun',
      params: { projectId: activeProjectId.value, predictionRunId: props.simulationId },
      query
    })
  }
}

// State
const agentLogs = ref([])
const consoleLogs = ref([])
const agentLogLine = ref(0)
const consoleLogLine = ref(0)
const reportOutline = ref(null)
const reportSnapshot = ref(null)
const currentSectionIndex = ref(null)
const generatedSections = ref({})
const expandedContent = ref(new Set())
const expandedLogs = ref(new Set())
const collapsedSections = ref(new Set())
const isComplete = ref(false)
const isFailed = ref(false)
const isRegeneratingReport = ref(false)
const reportStatus = ref('pending')
const startTime = ref(null)
const leftPanel = ref(null)
const rightPanel = ref(null)
const logContent = ref(null)
const showRawResult = reactive({})
const predictionStatus = ref(null)
const activeEvidenceTab = ref('overview')
const isFootballPredictionMode = computed(() => props.isFootballPrediction === true)

// Toggle functions
const setEvidenceTab = (tabKey) => {
  activeEvidenceTab.value = tabKey
}

const jumpToReportSectionByTitle = (title) => {
  const sections = reportOutline.value?.sections || []
  const index = sections.findIndex(section => section.title === title)
  if (index >= 0) {
    jumpToReportSection({ title }, index)
  }
}

const jumpToReportSection = (step, fallbackIndex = 0) => {
  const sections = reportOutline.value?.sections || []
  const indexFromTitle = sections.findIndex(section => section.title === step?.title)
  const index = indexFromTitle >= 0 ? indexFromTitle : fallbackIndex
  if (index < 0) return

  const newSet = new Set(collapsedSections.value)
  newSet.delete(index)
  collapsedSections.value = newSet

  nextTick(() => {
    const target = leftPanel.value?.querySelectorAll('.report-section-item')?.[index]
    target?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  })
}

const toggleRawResult = (timestamp, event) => {
  // 保存按钮相对于视口的位置
  const button = event?.target
  const buttonRect = button?.getBoundingClientRect()
  const buttonTopBeforeToggle = buttonRect?.top
  
  // 切换状态
  showRawResult[timestamp] = !showRawResult[timestamp]
  
  // 等待 DOM 更新后，调整滚动位置以保持按钮在相同位置
  if (button && buttonTopBeforeToggle !== undefined && rightPanel.value) {
    nextTick(() => {
      const newButtonRect = button.getBoundingClientRect()
      const buttonTopAfterToggle = newButtonRect.top
      const scrollDelta = buttonTopAfterToggle - buttonTopBeforeToggle
      
      // 调整滚动位置
      rightPanel.value.scrollTop += scrollDelta
    })
  }
}

const toggleSectionContent = (idx) => {
  if (!generatedSections.value[idx + 1]) return
  const newSet = new Set(expandedContent.value)
  if (newSet.has(idx)) {
    newSet.delete(idx)
  } else {
    newSet.add(idx)
  }
  expandedContent.value = newSet
}

const toggleSectionCollapse = (idx) => {
  // 只有已完成的章节才能折叠
  if (!generatedSections.value[idx + 1]) return
  const newSet = new Set(collapsedSections.value)
  if (newSet.has(idx)) {
    newSet.delete(idx)
  } else {
    newSet.add(idx)
  }
  collapsedSections.value = newSet
}

const toggleLogExpand = (log) => {
  const newSet = new Set(expandedLogs.value)
  if (newSet.has(log.timestamp)) {
    newSet.delete(log.timestamp)
  } else {
    newSet.add(log.timestamp)
  }
  expandedLogs.value = newSet
}

const isLogCollapsed = (log) => {
  if (['tool_call', 'tool_result', 'llm_response'].includes(log.action)) {
    return !expandedLogs.value.has(log.timestamp)
  }
  return false
}

// Tool configurations with display names and colors
const toolConfig = {
  'insight_forge': {
    name: 'Deep Insight',
    color: 'purple',
    icon: 'lightbulb' // 灯泡图标 - 代表洞察
  },
  'panorama_search': {
    name: 'Panorama Search',
    color: 'blue',
    icon: 'globe' // 地球图标 - 代表全景搜索
  },
  'interview_agents': {
    name: 'Analyst Review',
    color: 'green',
    icon: 'users' // 用户图标 - 代表研判角色
  },
  'quick_search': {
    name: 'Quick Search',
    color: 'orange',
    icon: 'zap' // 闪电图标 - 代表快速
  },
  'get_graph_statistics': {
    name: 'Graph Stats',
    color: 'cyan',
    icon: 'chart' // 图表图标 - 代表统计
  },
  'get_entities_by_type': {
    name: 'Entity Query',
    color: 'pink',
    icon: 'database' // 数据库图标 - 代表实体
  }
}

const getToolDisplayName = (toolName) => {
  return toolConfig[toolName]?.name || toolName
}

const getToolColor = (toolName) => {
  return toolConfig[toolName]?.color || 'gray'
}

const getToolIcon = (toolName) => {
  return toolConfig[toolName]?.icon || 'tool'
}

// Parse functions
const parseInsightForge = (text) => {
  const result = {
    query: '',
    simulationRequirement: '',
    stats: { facts: 0, entities: 0, relationships: 0 },
    subQueries: [],
    facts: [],
    entities: [],
    relations: []
  }
  
  try {
    // 提取分析问题
    const queryMatch = text.match(/分析问题:\s*(.+?)(?:\n|$)/)
    if (queryMatch) result.query = queryMatch[1].trim()
    
    // 提取预测场景
    const reqMatch = text.match(/预测场景:\s*(.+?)(?:\n|$)/)
    if (reqMatch) result.simulationRequirement = reqMatch[1].trim()
    
    // 提取统计数据 - 匹配"相关预测事实: X条"格式
    const factMatch = text.match(/相关预测事实:\s*(\d+)/)
    const entityMatch = text.match(/涉及实体:\s*(\d+)/)
    const relMatch = text.match(/关系链:\s*(\d+)/)
    if (factMatch) result.stats.facts = parseInt(factMatch[1])
    if (entityMatch) result.stats.entities = parseInt(entityMatch[1])
    if (relMatch) result.stats.relationships = parseInt(relMatch[1])
    
    // 提取子问题 - 完整提取，不限制数量
    const subQSection = text.match(/### 分析的子问题\n([\s\S]*?)(?=\n###|$)/)
    if (subQSection) {
      const lines = subQSection[1].split('\n').filter(l => l.match(/^\d+\./))
      result.subQueries = lines.map(l => l.replace(/^\d+\.\s*/, '').trim()).filter(Boolean)
    }
    
    // 提取关键事实 - 完整提取，不限制数量
    const factsSection = text.match(/### 【关键事实】[\s\S]*?\n([\s\S]*?)(?=\n###|$)/)
    if (factsSection) {
      const lines = factsSection[1].split('\n').filter(l => l.match(/^\d+\./))
      result.facts = lines.map(l => {
        const match = l.match(/^\d+\.\s*"?(.+?)"?\s*$/)
        return match ? match[1].replace(/^"|"$/g, '').trim() : l.replace(/^\d+\.\s*/, '').trim()
      }).filter(Boolean)
    }
    
    // 提取核心实体 - 完整提取，包含摘要和相关事实数
    const entitySection = text.match(/### 【核心实体】\n([\s\S]*?)(?=\n###|$)/)
    if (entitySection) {
      const entityText = entitySection[1]
      // 按 "- **" 分割实体块
      const entityBlocks = entityText.split(/\n(?=- \*\*)/).filter(b => b.trim().startsWith('- **'))
      result.entities = entityBlocks.map(block => {
        const nameMatch = block.match(/^-\s*\*\*(.+?)\*\*\s*\((.+?)\)/)
        const summaryMatch = block.match(/摘要:\s*"?(.+?)"?(?:\n|$)/)
        const relatedMatch = block.match(/相关事实:\s*(\d+)/)
        return {
          name: nameMatch ? nameMatch[1].trim() : '',
          type: nameMatch ? nameMatch[2].trim() : '',
          summary: summaryMatch ? summaryMatch[1].trim() : '',
          relatedFactsCount: relatedMatch ? parseInt(relatedMatch[1]) : 0
        }
      }).filter(e => e.name)
    }
    
    // 提取关系链 - 完整提取，不限制数量
    const relSection = text.match(/### 【关系链】\n([\s\S]*?)(?=\n###|$)/)
    if (relSection) {
      const lines = relSection[1].split('\n').filter(l => l.trim().startsWith('-'))
      result.relations = lines.map(l => {
        const match = l.match(/^-\s*(.+?)\s*--\[(.+?)\]-->\s*(.+)$/)
        if (match) {
          return { source: match[1].trim(), relation: match[2].trim(), target: match[3].trim() }
        }
        return null
      }).filter(Boolean)
    }
  } catch (e) {
    console.warn('Parse insight_forge failed:', e)
  }
  
  return result
}

const parsePanorama = (text) => {
  const result = {
    query: '',
    stats: { nodes: 0, edges: 0, activeFacts: 0, historicalFacts: 0 },
    activeFacts: [],
    historicalFacts: [],
    entities: []
  }
  
  try {
    // 提取查询
    const queryMatch = text.match(/查询:\s*(.+?)(?:\n|$)/)
    if (queryMatch) result.query = queryMatch[1].trim()
    
    // 提取统计数据
    const nodesMatch = text.match(/总节点数:\s*(\d+)/)
    const edgesMatch = text.match(/总边数:\s*(\d+)/)
    const activeMatch = text.match(/当前有效事实:\s*(\d+)/)
    const histMatch = text.match(/历史\/过期事实:\s*(\d+)/)
    if (nodesMatch) result.stats.nodes = parseInt(nodesMatch[1])
    if (edgesMatch) result.stats.edges = parseInt(edgesMatch[1])
    if (activeMatch) result.stats.activeFacts = parseInt(activeMatch[1])
    if (histMatch) result.stats.historicalFacts = parseInt(histMatch[1])
    
    // 提取当前有效事实 - 完整提取，不限制数量
    const activeSection = text.match(/### 【当前有效事实】[\s\S]*?\n([\s\S]*?)(?=\n###|$)/)
    if (activeSection) {
      const lines = activeSection[1].split('\n').filter(l => l.match(/^\d+\./))
      result.activeFacts = lines.map(l => {
        // 移除编号和引号
        const factText = l.replace(/^\d+\.\s*/, '').replace(/^"|"$/g, '').trim()
        return factText
      }).filter(Boolean)
    }
    
    // 提取历史/过期事实 - 完整提取，不限制数量
    const histSection = text.match(/### 【历史\/过期事实】[\s\S]*?\n([\s\S]*?)(?=\n###|$)/)
    if (histSection) {
      const lines = histSection[1].split('\n').filter(l => l.match(/^\d+\./))
      result.historicalFacts = lines.map(l => {
        const factText = l.replace(/^\d+\.\s*/, '').replace(/^"|"$/g, '').trim()
        return factText
      }).filter(Boolean)
    }
    
    // 提取涉及实体 - 完整提取，不限制数量
    const entitySection = text.match(/### 【涉及实体】\n([\s\S]*?)(?=\n###|$)/)
    if (entitySection) {
      const lines = entitySection[1].split('\n').filter(l => l.trim().startsWith('-'))
      result.entities = lines.map(l => {
        const match = l.match(/^-\s*\*\*(.+?)\*\*\s*\((.+?)\)/)
        if (match) return { name: match[1].trim(), type: match[2].trim() }
        return null
      }).filter(Boolean)
    }
  } catch (e) {
    console.warn('Parse panorama failed:', e)
  }
  
  return result
}

const parseInterview = (text) => {
  const result = {
    topic: '',
    agentCount: '',
    successCount: 0,
    totalCount: 0,
    selectionReason: '',
    interviews: [],
    summary: ''
  }
  
  try {
    // 提取研判主题
    const topicMatch = text.match(/\*\*采访主题:\*\*\s*(.+?)(?:\n|$)/)
    if (topicMatch) result.topic = topicMatch[1].trim()
    
    // 提取研判人数（如 "5 / 9 位分析角色"）
    const countMatch = text.match(/\*\*采访人数:\*\*\s*(\d+)\s*\/\s*(\d+)/)
    if (countMatch) {
      result.successCount = parseInt(countMatch[1])
      result.totalCount = parseInt(countMatch[2])
      result.agentCount = `${countMatch[1]} / ${countMatch[2]}`
    }
    
    // 提取研判对象选择理由
    const reasonMatch = text.match(/### 采访对象选择理由\n([\s\S]*?)(?=\n---\n|\n### 采访实录)/)
    if (reasonMatch) {
      result.selectionReason = reasonMatch[1].trim()
    }
    
    // 解析每个研判角色的选择理由
    const parseIndividualReasons = (reasonText) => {
      const reasons = {}
      if (!reasonText) return reasons
      
      const lines = reasonText.split(/\n+/)
      let currentName = null
      let currentReason = []
      
      for (const line of lines) {
        let headerMatch = null
        let name = null
        let reasonStart = null
        
        // 格式1: 数字. **名字（index=X）**：理由
        // 例如: 1. **校友_345（index=1）**：作为武大校友...
        headerMatch = line.match(/^\d+\.\s*\*\*([^*（(]+)(?:[（(]index\s*=?\s*\d+[)）])?\*\*[：:]\s*(.*)/)
        if (headerMatch) {
          name = headerMatch[1].trim()
          reasonStart = headerMatch[2]
        }
        
        // 格式2: - 选择名字（index X）：理由
        // 例如: - 选择家长_601（index 0）：作为家长群体代表...
        if (!headerMatch) {
          headerMatch = line.match(/^-\s*选择([^（(]+)(?:[（(]index\s*=?\s*\d+[)）])?[：:]\s*(.*)/)
          if (headerMatch) {
            name = headerMatch[1].trim()
            reasonStart = headerMatch[2]
          }
        }
        
        // 格式3: - **名字（index X）**：理由
        // 例如: - **家长_601（index 0）**：作为家长群体代表...
        if (!headerMatch) {
          headerMatch = line.match(/^-\s*\*\*([^*（(]+)(?:[（(]index\s*=?\s*\d+[)）])?\*\*[：:]\s*(.*)/)
          if (headerMatch) {
            name = headerMatch[1].trim()
            reasonStart = headerMatch[2]
          }
        }
        
        if (name) {
          // 保存上一个人的理由
          if (currentName && currentReason.length > 0) {
            reasons[currentName] = currentReason.join(' ').trim()
          }
          // 开始新的人
          currentName = name
          currentReason = reasonStart ? [reasonStart.trim()] : []
        } else if (currentName && line.trim() && !line.match(/^未选|^综上|^最终选择/)) {
          // 理由的续行（排除结尾总结段落）
          currentReason.push(line.trim())
        }
      }
      
      // 保存最后一个人的理由
      if (currentName && currentReason.length > 0) {
        reasons[currentName] = currentReason.join(' ').trim()
      }
      
      return reasons
    }
    
    const individualReasons = parseIndividualReasons(result.selectionReason)
    
      // 提取每个研判记录
      const interviewBlocks = text.split(/#### 采访 #\d+:/).slice(1)
    
    interviewBlocks.forEach((block, index) => {
      const interview = {
        num: index + 1,
        title: '',
        name: '',
        role: '',
        bio: '',
        selectionReason: '',
        questions: [],
        primaryAnswer: '',
        alternateAnswer: '',
        quotes: []
      }
      
      // 提取标题（如 "学生"、"教育从业者" 等）
      const titleMatch = block.match(/^(.+?)\n/)
      if (titleMatch) interview.title = titleMatch[1].trim()
      
      // 提取姓名和角色
      const nameRoleMatch = block.match(/\*\*(.+?)\*\*\s*\((.+?)\)/)
      if (nameRoleMatch) {
        interview.name = nameRoleMatch[1].trim()
        interview.role = nameRoleMatch[2].trim()
        // 设置该人的选择理由
        interview.selectionReason = individualReasons[interview.name] || ''
      }
      
      // 提取简介
      const bioMatch = block.match(/_简介:\s*([\s\S]*?)_\n/)
      if (bioMatch) {
        interview.bio = bioMatch[1].trim().replace(/\.\.\.$/, '...')
      }
      
      // 提取问题列表
      const qMatch = block.match(/\*\*Q:\*\*\s*([\s\S]*?)(?=\n\n\*\*A:\*\*|\*\*A:\*\*)/)
      if (qMatch) {
        const qText = qMatch[1].trim()
        // 按数字编号分割问题
        const questions = qText.split(/\n\d+\.\s+/).filter(q => q.trim())
        if (questions.length > 0) {
          // 如果第一个问题前面有"1."，需要特殊处理
          const firstQ = qText.match(/^1\.\s+(.+)/)
          if (firstQ) {
            interview.questions = [firstQ[1].trim(), ...questions.slice(1).map(q => q.trim())]
          } else {
            interview.questions = questions.map(q => q.trim())
          }
        }
      }
      
      // 提取回答
      const answerMatch = block.match(/\*\*A:\*\*\s*([\s\S]*?)(?=\*\*关键引言|$)/)
      if (answerMatch) {
        const answerText = answerMatch[1].trim()
        const baselineMatch = answerText.match(/【基准研判】\n?([\s\S]*?)(?=【扰动研判】|$)/)
        const scenarioMatch = answerText.match(/【扰动研判】\n?([\s\S]*?)$/)
        interview.primaryAnswer = (baselineMatch?.[1] || answerText).trim()
        interview.alternateAnswer = scenarioMatch?.[1]?.trim() || ''
      }
      
      // 提取关键引言（兼容多种引号格式）
      const quotesMatch = block.match(/\*\*关键引言:\*\*\n([\s\S]*?)(?=\n---|\n####|$)/)
      if (quotesMatch) {
        const quotesText = quotesMatch[1]
        // 优先匹配 > "text" 格式
        let quoteMatches = quotesText.match(/> "([^"]+)"/g)
        // 回退：匹配 > "text" 或 > \u201Ctext\u201D（中文引号）
        if (!quoteMatches) {
          quoteMatches = quotesText.match(/> [\u201C""]([^\u201D""]+)[\u201D""]/g)
        }
        if (quoteMatches) {
          interview.quotes = quoteMatches
            .map(q => q.replace(/^> [\u201C""]|[\u201D""]$/g, '').trim())
            .filter(q => q)
        }
      }
      
      if (interview.name || interview.title) {
        result.interviews.push(interview)
      }
    })
    
    // 提取研判摘要
    const summaryMatch = text.match(/### 采访摘要与核心观点\n([\s\S]*?)$/)
    if (summaryMatch) {
      result.summary = summaryMatch[1].trim()
    }
  } catch (e) {
    console.warn('Parse interview failed:', e)
  }
  
  return result
}

const parseQuickSearch = (text) => {
  const result = {
    query: '',
    count: 0,
    facts: [],
    edges: [],
    nodes: []
  }
  
  try {
    // 提取搜索查询
    const queryMatch = text.match(/搜索查询:\s*(.+?)(?:\n|$)/)
    if (queryMatch) result.query = queryMatch[1].trim()
    
    // 提取结果数量
    const countMatch = text.match(/找到\s*(\d+)\s*条/)
    if (countMatch) result.count = parseInt(countMatch[1])
    
    // 提取相关事实 - 完整提取，不限制数量
    const factsSection = text.match(/### 相关事实:\n([\s\S]*)$/)
    if (factsSection) {
      const lines = factsSection[1].split('\n').filter(l => l.match(/^\d+\./))
      result.facts = lines.map(l => l.replace(/^\d+\.\s*/, '').trim()).filter(Boolean)
    }
    
    // 尝试提取边信息（如果有）
    const edgesSection = text.match(/### 相关边:\n([\s\S]*?)(?=\n###|$)/)
    if (edgesSection) {
      const lines = edgesSection[1].split('\n').filter(l => l.trim().startsWith('-'))
      result.edges = lines.map(l => {
        const match = l.match(/^-\s*(.+?)\s*--\[(.+?)\]-->\s*(.+)$/)
        if (match) {
          return { source: match[1].trim(), relation: match[2].trim(), target: match[3].trim() }
        }
        return null
      }).filter(Boolean)
    }
    
    // 尝试提取节点信息（如果有）
    const nodesSection = text.match(/### 相关节点:\n([\s\S]*?)(?=\n###|$)/)
    if (nodesSection) {
      const lines = nodesSection[1].split('\n').filter(l => l.trim().startsWith('-'))
      result.nodes = lines.map(l => {
        const match = l.match(/^-\s*\*\*(.+?)\*\*\s*\((.+?)\)/)
        if (match) return { name: match[1].trim(), type: match[2].trim() }
        const simpleMatch = l.match(/^-\s*(.+)$/)
        if (simpleMatch) return { name: simpleMatch[1].trim(), type: '' }
        return null
      }).filter(Boolean)
    }
  } catch (e) {
    console.warn('Parse quick_search failed:', e)
  }
  
  return result
}

// ========== Sub Components ==========

// Insight Display Component - Enhanced with full data rendering (Interview-like style)
const InsightDisplay = {
  props: ['result', 'resultLength'],
  setup(props) {
    const { t } = useI18n()
    const activeTab = ref('facts') // 'facts', 'entities', 'relations', 'subqueries'
    const expandedFacts = ref(false)
    const expandedEntities = ref(false)
    const expandedRelations = ref(false)
    const INITIAL_SHOW_COUNT = 5
    
    // Format result size for display
    const formatSize = (length) => {
      if (!length) return ''
      if (length >= 1000) {
        return `${(length / 1000).toFixed(1)}k chars`
      }
      return `${length} chars`
    }
    
    return () => h('div', { class: 'insight-display' }, [
      // Header Section - like interview header
      h('div', { class: 'insight-header' }, [
        h('div', { class: 'header-main' }, [
          h('div', { class: 'header-title' }, 'Deep Insight'),
          h('div', { class: 'header-stats' }, [
            h('span', { class: 'stat-item' }, [
              h('span', { class: 'stat-value' }, props.result.stats.facts || props.result.facts.length),
              h('span', { class: 'stat-label' }, 'Facts')
            ]),
            h('span', { class: 'stat-divider' }, '/'),
            h('span', { class: 'stat-item' }, [
              h('span', { class: 'stat-value' }, props.result.stats.entities || props.result.entities.length),
              h('span', { class: 'stat-label' }, 'Entities')
            ]),
            h('span', { class: 'stat-divider' }, '/'),
            h('span', { class: 'stat-item' }, [
              h('span', { class: 'stat-value' }, props.result.stats.relationships || props.result.relations.length),
              h('span', { class: 'stat-label' }, 'Relations')
            ]),
            props.resultLength && h('span', { class: 'stat-divider' }, '·'),
            props.resultLength && h('span', { class: 'stat-size' }, formatSize(props.resultLength))
          ])
        ]),
        props.result.query && h('div', { class: 'header-topic' }, props.result.query),
        props.result.simulationRequirement && h('div', { class: 'header-scenario' }, [
          h('span', { class: 'scenario-label' }, t('step4.scenarioLabel')),
          h('span', { class: 'scenario-text' }, props.result.simulationRequirement)
        ])
      ]),
      
      // Tab Navigation
      h('div', { class: 'insight-tabs' }, [
        h('button', {
          class: ['insight-tab', { active: activeTab.value === 'facts' }],
          onClick: () => { activeTab.value = 'facts' }
        }, [
          h('span', { class: 'tab-label' }, t('step4.tabKeyFacts', { count: props.result.facts.length }))
        ]),
        h('button', {
          class: ['insight-tab', { active: activeTab.value === 'entities' }],
          onClick: () => { activeTab.value = 'entities' }
        }, [
          h('span', { class: 'tab-label' }, t('step4.tabCoreEntities', { count: props.result.entities.length }))
        ]),
        h('button', {
          class: ['insight-tab', { active: activeTab.value === 'relations' }],
          onClick: () => { activeTab.value = 'relations' }
        }, [
          h('span', { class: 'tab-label' }, t('step4.tabRelationChains', { count: props.result.relations.length }))
        ]),
        props.result.subQueries.length > 0 && h('button', {
          class: ['insight-tab', { active: activeTab.value === 'subqueries' }],
          onClick: () => { activeTab.value = 'subqueries' }
        }, [
          h('span', { class: 'tab-label' }, t('step4.tabSubQueries', { count: props.result.subQueries.length }))
        ])
      ]),
      
      // Tab Content
      h('div', { class: 'insight-content' }, [
        // Facts Tab
        activeTab.value === 'facts' && props.result.facts.length > 0 && h('div', { class: 'facts-panel' }, [
          h('div', { class: 'panel-header' }, [
            h('span', { class: 'panel-title' }, t('step4.panelKeyFacts')),
            h('span', { class: 'panel-count' }, t('step4.totalCount', { count: props.result.facts.length }))
          ]),
          h('div', { class: 'facts-list' },
            (expandedFacts.value ? props.result.facts : props.result.facts.slice(0, INITIAL_SHOW_COUNT)).map((fact, i) => 
              h('div', { class: 'fact-item', key: i }, [
                h('span', { class: 'fact-number' }, i + 1),
                h('div', { class: 'fact-content' }, fact)
              ])
            )
          ),
          props.result.facts.length > INITIAL_SHOW_COUNT && h('button', {
            class: 'expand-btn',
            onClick: () => { expandedFacts.value = !expandedFacts.value }
          }, expandedFacts.value ? t('step4.collapse') : t('step4.expandAll', { count: props.result.facts.length }))
        ]),

        // Entities Tab
        activeTab.value === 'entities' && props.result.entities.length > 0 && h('div', { class: 'entities-panel' }, [
          h('div', { class: 'panel-header' }, [
            h('span', { class: 'panel-title' }, t('step4.panelCoreEntities')),
            h('span', { class: 'panel-count' }, t('step4.totalEntityCount', { count: props.result.entities.length }))
          ]),
          h('div', { class: 'entities-grid' },
            (expandedEntities.value ? props.result.entities : props.result.entities.slice(0, 12)).map((entity, i) => 
              h('div', { class: 'entity-tag', key: i, title: entity.summary || '' }, [
                h('span', { class: 'entity-name' }, entity.name),
                h('span', { class: 'entity-type' }, entity.type),
                entity.relatedFactsCount > 0 && h('span', { class: 'entity-fact-count' }, t('step4.factCount', { count: entity.relatedFactsCount }))
              ])
            )
          ),
          props.result.entities.length > 12 && h('button', {
            class: 'expand-btn',
            onClick: () => { expandedEntities.value = !expandedEntities.value }
          }, expandedEntities.value ? t('step4.collapse') : t('step4.expandAllEntities', { count: props.result.entities.length }))
        ]),

        // Relations Tab
        activeTab.value === 'relations' && props.result.relations.length > 0 && h('div', { class: 'relations-panel' }, [
          h('div', { class: 'panel-header' }, [
            h('span', { class: 'panel-title' }, t('step4.panelRelationChains')),
            h('span', { class: 'panel-count' }, t('step4.totalCount', { count: props.result.relations.length }))
          ]),
          h('div', { class: 'relations-list' },
            (expandedRelations.value ? props.result.relations : props.result.relations.slice(0, INITIAL_SHOW_COUNT)).map((rel, i) => 
              h('div', { class: 'relation-item', key: i }, [
                h('span', { class: 'rel-source' }, rel.source),
                h('span', { class: 'rel-arrow' }, [
                  h('span', { class: 'rel-line' }),
                  h('span', { class: 'rel-label' }, rel.relation),
                  h('span', { class: 'rel-line' })
                ]),
                h('span', { class: 'rel-target' }, rel.target)
              ])
            )
          ),
          props.result.relations.length > INITIAL_SHOW_COUNT && h('button', {
            class: 'expand-btn',
            onClick: () => { expandedRelations.value = !expandedRelations.value }
          }, expandedRelations.value ? t('step4.collapse') : t('step4.expandAll', { count: props.result.relations.length }))
        ]),

        // Sub-queries Tab
        activeTab.value === 'subqueries' && props.result.subQueries.length > 0 && h('div', { class: 'subqueries-panel' }, [
          h('div', { class: 'panel-header' }, [
            h('span', { class: 'panel-title' }, t('step4.panelSubQueries')),
            h('span', { class: 'panel-count' }, t('step4.totalEntityCount', { count: props.result.subQueries.length }))
          ]),
          h('div', { class: 'subqueries-list' },
            props.result.subQueries.map((sq, i) => 
              h('div', { class: 'subquery-item', key: i }, [
                h('span', { class: 'subquery-number' }, `Q${i + 1}`),
                h('div', { class: 'subquery-text' }, sq)
              ])
            )
          )
        ]),
        
        // Empty state
        activeTab.value === 'facts' && props.result.facts.length === 0 && h('div', { class: 'empty-state' }, t('step4.emptyKeyFacts')),
        activeTab.value === 'entities' && props.result.entities.length === 0 && h('div', { class: 'empty-state' }, t('step4.emptyCoreEntities')),
        activeTab.value === 'relations' && props.result.relations.length === 0 && h('div', { class: 'empty-state' }, t('step4.emptyRelationChains'))
      ])
    ])
  }
}

// Panorama Display Component - Enhanced with Active/Historical tabs
const PanoramaDisplay = {
  props: ['result', 'resultLength'],
  setup(props) {
    const { t } = useI18n()
    const activeTab = ref('active') // 'active', 'historical', 'entities'
    const expandedActive = ref(false)
    const expandedHistorical = ref(false)
    const expandedEntities = ref(false)
    const INITIAL_SHOW_COUNT = 5
    
    // Format result size for display
    const formatSize = (length) => {
      if (!length) return ''
      if (length >= 1000) {
        return `${(length / 1000).toFixed(1)}k chars`
      }
      return `${length} chars`
    }
    
    return () => h('div', { class: 'panorama-display' }, [
      // Header Section
      h('div', { class: 'panorama-header' }, [
        h('div', { class: 'header-main' }, [
          h('div', { class: 'header-title' }, 'Panorama Search'),
          h('div', { class: 'header-stats' }, [
            h('span', { class: 'stat-item' }, [
              h('span', { class: 'stat-value' }, props.result.stats.nodes),
              h('span', { class: 'stat-label' }, 'Nodes')
            ]),
            h('span', { class: 'stat-divider' }, '/'),
            h('span', { class: 'stat-item' }, [
              h('span', { class: 'stat-value' }, props.result.stats.edges),
              h('span', { class: 'stat-label' }, 'Edges')
            ]),
            props.resultLength && h('span', { class: 'stat-divider' }, '·'),
            props.resultLength && h('span', { class: 'stat-size' }, formatSize(props.resultLength))
          ])
        ]),
        props.result.query && h('div', { class: 'header-topic' }, props.result.query)
      ]),
      
      // Tab Navigation
      h('div', { class: 'panorama-tabs' }, [
        h('button', {
          class: ['panorama-tab', { active: activeTab.value === 'active' }],
          onClick: () => { activeTab.value = 'active' }
        }, [
          h('span', { class: 'tab-label' }, t('step4.tabActiveFacts', { count: props.result.activeFacts.length }))
        ]),
        h('button', {
          class: ['panorama-tab', { active: activeTab.value === 'historical' }],
          onClick: () => { activeTab.value = 'historical' }
        }, [
          h('span', { class: 'tab-label' }, t('step4.tabHistoricalFacts', { count: props.result.historicalFacts.length }))
        ]),
        h('button', {
          class: ['panorama-tab', { active: activeTab.value === 'entities' }],
          onClick: () => { activeTab.value = 'entities' }
        }, [
          h('span', { class: 'tab-label' }, t('step4.tabEntities', { count: props.result.entities.length }))
        ])
      ]),
      
      // Tab Content
      h('div', { class: 'panorama-content' }, [
        // Active Facts Tab
        activeTab.value === 'active' && h('div', { class: 'facts-panel active-facts' }, [
          h('div', { class: 'panel-header' }, [
            h('span', { class: 'panel-title' }, t('step4.panelActiveFacts')),
            h('span', { class: 'panel-count' }, t('step4.totalCount', { count: props.result.activeFacts.length }))
          ]),
          props.result.activeFacts.length > 0 ? h('div', { class: 'facts-list' },
            (expandedActive.value ? props.result.activeFacts : props.result.activeFacts.slice(0, INITIAL_SHOW_COUNT)).map((fact, i) => 
              h('div', { class: 'fact-item active', key: i }, [
                h('span', { class: 'fact-number' }, i + 1),
                h('div', { class: 'fact-content' }, fact)
              ])
            )
          ) : h('div', { class: 'empty-state' }, t('step4.emptyActiveFacts')),
          props.result.activeFacts.length > INITIAL_SHOW_COUNT && h('button', {
            class: 'expand-btn',
            onClick: () => { expandedActive.value = !expandedActive.value }
          }, expandedActive.value ? t('step4.collapse') : t('step4.expandAll', { count: props.result.activeFacts.length }))
        ]),
        
        // Historical Facts Tab
        activeTab.value === 'historical' && h('div', { class: 'facts-panel historical-facts' }, [
          h('div', { class: 'panel-header' }, [
            h('span', { class: 'panel-title' }, t('step4.panelHistoricalFacts')),
            h('span', { class: 'panel-count' }, t('step4.totalCount', { count: props.result.historicalFacts.length }))
          ]),
          props.result.historicalFacts.length > 0 ? h('div', { class: 'facts-list' },
            (expandedHistorical.value ? props.result.historicalFacts : props.result.historicalFacts.slice(0, INITIAL_SHOW_COUNT)).map((fact, i) => 
              h('div', { class: 'fact-item historical', key: i }, [
                h('span', { class: 'fact-number' }, i + 1),
                h('div', { class: 'fact-content' }, [
                  // 尝试提取时间信息 [time - time]
                  (() => {
                    const timeMatch = fact.match(/^\[(.+?)\]\s*(.*)$/)
                    if (timeMatch) {
                      return [
                        h('span', { class: 'fact-time' }, timeMatch[1]),
                        h('span', { class: 'fact-text' }, timeMatch[2])
                      ]
                    }
                    return h('span', { class: 'fact-text' }, fact)
                  })()
                ])
              ])
            )
          ) : h('div', { class: 'empty-state' }, t('step4.emptyHistoricalFacts')),
          props.result.historicalFacts.length > INITIAL_SHOW_COUNT && h('button', {
            class: 'expand-btn',
            onClick: () => { expandedHistorical.value = !expandedHistorical.value }
          }, expandedHistorical.value ? t('step4.collapse') : t('step4.expandAll', { count: props.result.historicalFacts.length }))
        ]),
        
        // Entities Tab
        activeTab.value === 'entities' && h('div', { class: 'entities-panel' }, [
          h('div', { class: 'panel-header' }, [
            h('span', { class: 'panel-title' }, t('step4.panelEntities')),
            h('span', { class: 'panel-count' }, t('step4.totalEntityCount', { count: props.result.entities.length }))
          ]),
          props.result.entities.length > 0 ? h('div', { class: 'entities-grid' },
            (expandedEntities.value ? props.result.entities : props.result.entities.slice(0, 8)).map((entity, i) => 
              h('div', { class: 'entity-tag', key: i }, [
                h('span', { class: 'entity-name' }, entity.name),
                entity.type && h('span', { class: 'entity-type' }, entity.type)
              ])
            )
          ) : h('div', { class: 'empty-state' }, t('step4.emptyEntities')),
          props.result.entities.length > 8 && h('button', {
            class: 'expand-btn',
            onClick: () => { expandedEntities.value = !expandedEntities.value }
          }, expandedEntities.value ? t('step4.collapse') : t('step4.expandAllEntities', { count: props.result.entities.length }))
        ])
      ])
    ])
  }
}

// Analyst Review Display Component - Conversation Style (Q&A Format)
const InterviewDisplay = {
  props: ['result', 'resultLength'],
  setup(props) {
    // Format result size for display
    const formatSize = (length) => {
      if (!length) return ''
      if (length >= 1000) {
        return `${(length / 1000).toFixed(1)}k chars`
      }
      return `${length} chars`
    }
    
    // Clean quote text - remove leading list numbers to avoid double numbering
    const cleanQuoteText = (text) => {
      if (!text) return ''
      // Remove leading patterns like "1. ", "2. ", "1、", "（1）", "(1)" etc.
      return text.replace(/^\s*\d+[\.\、\)）]\s*/, '').trim()
    }
    
    const activeIndex = ref(0)
    const expandedAnswers = ref(new Set())
    
    const toggleAnswer = (key) => {
      const newSet = new Set(expandedAnswers.value)
      if (newSet.has(key)) {
        newSet.delete(key)
      } else {
        newSet.add(key)
      }
      expandedAnswers.value = newSet
    }
    
    const formatAnswer = (text, expanded) => {
      if (!text) return ''
      if (expanded || text.length <= 400) return text
      return text.substring(0, 400) + '...'
    }
    
    // 检查是否为未回复占位文本
    const isPlaceholderText = (text) => {
      if (!text) return true
      const t = text.trim()
      return ['（未获得回复）', '(未获得回复)', '[无回复]'].includes(t)
    }

    // 尝试按问题编号分割回答
    const splitAnswerByQuestions = (answerText, questionCount) => {
      if (!answerText || questionCount <= 0) return [answerText]
      if (isPlaceholderText(answerText)) return ['']

      // 支持两种编号格式：
      // 1. "问题X：" 或 "问题X:" （中文格式，后端新格式）
      // 2. "1. " 或 "\n1. " （数字+点，旧格式兼容）
      let matches = []
      let match

      // 优先尝试 "问题X：" 格式
      const cnPattern = /(?:^|[\r\n]+)问题(\d+)[：:]\s*/g
      while ((match = cnPattern.exec(answerText)) !== null) {
        matches.push({
          num: parseInt(match[1]),
          index: match.index,
          fullMatch: match[0]
        })
      }

      // 如果没匹配到，回退到 "数字." 格式
      if (matches.length === 0) {
        const numPattern = /(?:^|[\r\n]+)(\d+)\.\s+/g
        while ((match = numPattern.exec(answerText)) !== null) {
          matches.push({
            num: parseInt(match[1]),
            index: match.index,
            fullMatch: match[0]
          })
        }
      }

      // 如果没有找到编号或只找到一个，返回整体
      if (matches.length <= 1) {
        const cleaned = answerText
          .replace(/^问题\d+[：:]\s*/, '')
          .replace(/^\d+\.\s+/, '')
          .trim()
        return [cleaned || answerText]
      }

      // 按编号提取各部分
      const parts = []
      for (let i = 0; i < matches.length; i++) {
        const current = matches[i]
        const next = matches[i + 1]

        const startIdx = current.index + current.fullMatch.length
        const endIdx = next ? next.index : answerText.length

        let part = answerText.substring(startIdx, endIdx).trim()
        part = part.replace(/[\r\n]+$/, '').trim()
        parts.push(part)
      }

      if (parts.length > 0 && parts.some(p => p)) {
        return parts
      }

      return [answerText]
    }
    
    // 获取某个问题对应的回答
    const getAnswerForQuestion = (interview, qIdx) => {
      const answer = interview.primaryAnswer || interview.alternateAnswer
      if (!answer || isPlaceholderText(answer)) return answer || ''

      const questionCount = interview.questions?.length || 1
      const answers = splitAnswerByQuestions(answer, questionCount)

      // 分割成功且索引有效
      if (answers.length > 1 && qIdx < answers.length) {
        return answers[qIdx] || ''
      }

      // 分割失败：第一个问题返回完整回答，其余返回空
      return qIdx === 0 ? answer : ''
    }
    
    return () => h('div', { class: 'interview-display' }, [
      // Header Section
      h('div', { class: 'interview-header' }, [
        h('div', { class: 'header-main' }, [
          h('div', { class: 'header-title' }, 'Analyst Review'),
          h('div', { class: 'header-stats' }, [
            h('span', { class: 'stat-item' }, [
              h('span', { class: 'stat-value' }, props.result.successCount || props.result.interviews.length),
              h('span', { class: 'stat-label' }, 'Reviewed')
            ]),
            props.result.totalCount > 0 && h('span', { class: 'stat-divider' }, '/'),
            props.result.totalCount > 0 && h('span', { class: 'stat-item' }, [
              h('span', { class: 'stat-value' }, props.result.totalCount),
              h('span', { class: 'stat-label' }, 'Total')
            ]),
            props.resultLength && h('span', { class: 'stat-divider' }, '·'),
            props.resultLength && h('span', { class: 'stat-size' }, formatSize(props.resultLength))
          ])
        ]),
        props.result.topic && h('div', { class: 'header-topic' }, props.result.topic)
      ]),
      
      // Analyst Selector Tabs
      props.result.interviews.length > 0 && h('div', { class: 'agent-tabs' }, 
        props.result.interviews.map((interview, i) => h('button', {
          class: ['agent-tab', { active: activeIndex.value === i }],
          key: i,
          onClick: () => { activeIndex.value = i }
        }, [
          h('span', { class: 'tab-avatar' }, interview.name ? interview.name.charAt(0) : (i + 1)),
          h('span', { class: 'tab-name' }, interview.title || interview.name || `Analyst ${i + 1}`)
        ]))
      ),
      
      // Active Interview Detail
      props.result.interviews.length > 0 && h('div', { class: 'interview-detail' }, [
        // Analyst Profile Card
        h('div', { class: 'agent-profile' }, [
          h('div', { class: 'profile-avatar' }, props.result.interviews[activeIndex.value]?.name?.charAt(0) || 'A'),
          h('div', { class: 'profile-info' }, [
            h('div', { class: 'profile-name' }, props.result.interviews[activeIndex.value]?.name || 'Analyst'),
            h('div', { class: 'profile-role' }, props.result.interviews[activeIndex.value]?.role || ''),
            props.result.interviews[activeIndex.value]?.bio && h('div', { class: 'profile-bio' }, props.result.interviews[activeIndex.value].bio)
          ])
        ]),
        
        // Selection Reason - 选择理由
        props.result.interviews[activeIndex.value]?.selectionReason && h('div', { class: 'selection-reason' }, [
          h('div', { class: 'reason-label' }, '选择理由'),
          h('div', { class: 'reason-content' }, props.result.interviews[activeIndex.value].selectionReason)
        ]),
        
        // Q&A Conversation Thread - 一问一答样式
        h('div', { class: 'qa-thread' }, 
          (props.result.interviews[activeIndex.value]?.questions?.length > 0 
            ? props.result.interviews[activeIndex.value].questions 
            : [props.result.interviews[activeIndex.value]?.question || 'No review question available']
          ).map((question, qIdx) => {
            const interview = props.result.interviews[activeIndex.value]
            const answerText = getAnswerForQuestion(interview, qIdx)
            const expandKey = `${activeIndex.value}-${qIdx}`
            const isExpanded = expandedAnswers.value.has(expandKey)
            const isPlaceholder = isPlaceholderText(answerText)

            return h('div', { class: 'qa-pair', key: qIdx }, [
              // Question Block
              h('div', { class: 'qa-question' }, [
                h('div', { class: 'qa-badge q-badge' }, `Q${qIdx + 1}`),
                h('div', { class: 'qa-content' }, [
                  h('div', { class: 'qa-sender' }, 'Reviewer'),
                  h('div', { class: 'qa-text' }, question)
                ])
              ]),

              // Answer Block
              answerText && h('div', { class: ['qa-answer', { 'answer-placeholder': isPlaceholder }] }, [
                h('div', { class: 'qa-badge a-badge' }, `A${qIdx + 1}`),
                h('div', { class: 'qa-content' }, [
                  h('div', { class: 'qa-answer-header' }, [
                    h('div', { class: 'qa-sender' }, interview?.name || 'Analyst')
                  ]),
                  h('div', {
                    class: ['qa-text', 'answer-text', { 'placeholder-text': isPlaceholder }],
                    innerHTML: isPlaceholder
                      ? '（未获得回复）'
                      : formatAnswer(answerText, isExpanded)
                          .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
                          .replace(/\n/g, '<br>')
                  }),
                  // Expand/Collapse Button（占位文本不显示）
                  !isPlaceholder && answerText.length > 400 && h('button', {
                    class: 'expand-answer-btn',
                    onClick: () => toggleAnswer(expandKey)
                  }, isExpanded ? 'Show Less' : 'Show More')
                ])
              ])
            ])
          })
        ),
        
        // Key Quotes Section
        props.result.interviews[activeIndex.value]?.quotes?.length > 0 && h('div', { class: 'quotes-section' }, [
          h('div', { class: 'quotes-header' }, 'Key Quotes'),
          h('div', { class: 'quotes-list' },
            props.result.interviews[activeIndex.value].quotes.slice(0, 3).map((quote, qi) => {
              const cleanedQuote = cleanQuoteText(quote)
              const displayQuote = cleanedQuote.length > 200 ? cleanedQuote.substring(0, 200) + '...' : cleanedQuote
              return h('blockquote', { 
                key: qi, 
                class: 'quote-item',
                innerHTML: renderMarkdown(displayQuote)
              })
            })
          )
        ])
      ]),

      // Summary Section (Collapsible)
      props.result.summary && h('div', { class: 'summary-section' }, [
        h('div', { class: 'summary-header' }, 'Review Summary'),
        h('div', { 
          class: 'summary-content',
          innerHTML: renderMarkdown(props.result.summary.length > 500 ? props.result.summary.substring(0, 500) + '...' : props.result.summary)
        })
      ])
    ])
  }
}

// Quick Search Display Component - Enhanced with full data rendering
const QuickSearchDisplay = {
  props: ['result', 'resultLength'],
  setup(props) {
    const { t } = useI18n()
    const activeTab = ref('facts') // 'facts', 'edges', 'nodes'
    const expandedFacts = ref(false)
    const INITIAL_SHOW_COUNT = 5
    
    // Check if there are edges or nodes to show tabs
    const hasEdges = computed(() => props.result.edges && props.result.edges.length > 0)
    const hasNodes = computed(() => props.result.nodes && props.result.nodes.length > 0)
    const showTabs = computed(() => hasEdges.value || hasNodes.value)
    
    // Format result size for display
    const formatSize = (length) => {
      if (!length) return ''
      if (length >= 1000) {
        return `${(length / 1000).toFixed(1)}k chars`
      }
      return `${length} chars`
    }
    
    return () => h('div', { class: 'quick-search-display' }, [
      // Header Section
      h('div', { class: 'quicksearch-header' }, [
        h('div', { class: 'header-main' }, [
          h('div', { class: 'header-title' }, 'Quick Search'),
          h('div', { class: 'header-stats' }, [
            h('span', { class: 'stat-item' }, [
              h('span', { class: 'stat-value' }, props.result.count || props.result.facts.length),
              h('span', { class: 'stat-label' }, 'Results')
            ]),
            props.resultLength && h('span', { class: 'stat-divider' }, '·'),
            props.resultLength && h('span', { class: 'stat-size' }, formatSize(props.resultLength))
          ])
        ]),
        props.result.query && h('div', { class: 'header-query' }, [
          h('span', { class: 'query-label' }, t('step4.searchLabel')),
          h('span', { class: 'query-text' }, props.result.query)
        ])
      ]),
      
      // Tab Navigation (only show if there are edges or nodes)
      showTabs.value && h('div', { class: 'quicksearch-tabs' }, [
        h('button', {
          class: ['quicksearch-tab', { active: activeTab.value === 'facts' }],
          onClick: () => { activeTab.value = 'facts' }
        }, [
          h('span', { class: 'tab-label' }, t('step4.tabFacts', { count: props.result.facts.length }))
        ]),
        hasEdges.value && h('button', {
          class: ['quicksearch-tab', { active: activeTab.value === 'edges' }],
          onClick: () => { activeTab.value = 'edges' }
        }, [
          h('span', { class: 'tab-label' }, t('step4.tabEdges', { count: props.result.edges.length }))
        ]),
        hasNodes.value && h('button', {
          class: ['quicksearch-tab', { active: activeTab.value === 'nodes' }],
          onClick: () => { activeTab.value = 'nodes' }
        }, [
          h('span', { class: 'tab-label' }, t('step4.tabNodes', { count: props.result.nodes.length }))
        ])
      ]),
      
      // Content Area
      h('div', { class: ['quicksearch-content', { 'no-tabs': !showTabs.value }] }, [
        // Facts (always show if no tabs, or when facts tab is active)
        ((!showTabs.value) || activeTab.value === 'facts') && h('div', { class: 'facts-panel' }, [
          !showTabs.value && h('div', { class: 'panel-header' }, [
            h('span', { class: 'panel-title' }, t('step4.panelSearchResults')),
            h('span', { class: 'panel-count' }, t('step4.totalCount', { count: props.result.facts.length }))
          ]),
          props.result.facts.length > 0 ? h('div', { class: 'facts-list' },
            (expandedFacts.value ? props.result.facts : props.result.facts.slice(0, INITIAL_SHOW_COUNT)).map((fact, i) => 
              h('div', { class: 'fact-item', key: i }, [
                h('span', { class: 'fact-number' }, i + 1),
                h('div', { class: 'fact-content' }, fact)
              ])
            )
          ) : h('div', { class: 'empty-state' }, t('step4.emptySearchResults')),
          props.result.facts.length > INITIAL_SHOW_COUNT && h('button', {
            class: 'expand-btn',
            onClick: () => { expandedFacts.value = !expandedFacts.value }
          }, expandedFacts.value ? t('step4.collapse') : t('step4.expandAll', { count: props.result.facts.length }))
        ]),
        
        // Edges Tab
        activeTab.value === 'edges' && hasEdges.value && h('div', { class: 'edges-panel' }, [
          h('div', { class: 'panel-header' }, [
            h('span', { class: 'panel-title' }, t('step4.panelRelatedEdges')),
            h('span', { class: 'panel-count' }, t('step4.totalCount', { count: props.result.edges.length }))
          ]),
          h('div', { class: 'edges-list' },
            props.result.edges.map((edge, i) => 
              h('div', { class: 'edge-item', key: i }, [
                h('span', { class: 'edge-source' }, edge.source),
                h('span', { class: 'edge-arrow' }, [
                  h('span', { class: 'edge-line' }),
                  h('span', { class: 'edge-label' }, edge.relation),
                  h('span', { class: 'edge-line' })
                ]),
                h('span', { class: 'edge-target' }, edge.target)
              ])
            )
          )
        ]),
        
        // Nodes Tab
        activeTab.value === 'nodes' && hasNodes.value && h('div', { class: 'nodes-panel' }, [
          h('div', { class: 'panel-header' }, [
            h('span', { class: 'panel-title' }, t('step4.panelRelatedNodes')),
            h('span', { class: 'panel-count' }, t('step4.totalEntityCount', { count: props.result.nodes.length }))
          ]),
          h('div', { class: 'nodes-grid' },
            props.result.nodes.map((node, i) => 
              h('div', { class: 'node-tag', key: i }, [
                h('span', { class: 'node-name' }, node.name),
                node.type && h('span', { class: 'node-type' }, node.type)
              ])
            )
          )
        ])
      ])
    ])
  }
}

// Computed
const statusClass = computed(() => {
  if (isFailed.value) return 'error'
  if (isComplete.value) return 'completed'
  if (agentLogs.value.length > 0) return 'processing'
  return 'pending'
})

const statusText = computed(() => {
  if (isFailed.value) return 'Failed'
  if (isComplete.value) return 'Completed'
  if (agentLogs.value.length > 0) return 'Generating...'
  return 'Waiting'
})

const totalSections = computed(() => {
  return reportOutline.value?.sections?.length || 0
})

const completedSections = computed(() => {
  return Object.keys(generatedSections.value).length
})

const progressPercent = computed(() => {
  if (totalSections.value === 0) return 0
  return Math.round((completedSections.value / totalSections.value) * 100)
})

const totalToolCalls = computed(() => {
  return agentLogs.value.filter(l => l.action === 'tool_call').length
})

const predictionCounts = computed(() => predictionStatus.value?.counts || {})
const activePredictionRunId = computed(() => (
  props.predictionRunId
  || props.simulationId
  || reportSnapshot.value?.prediction_run_id
  || reportSnapshot.value?.simulation_id
  || reportSnapshot.value?.report_metadata?.prediction_run_id
))
const activePredictionConfigId = computed(() => (
  props.predictionConfigId
  || predictionStatus.value?.prediction_config_id
  || reportSnapshot.value?.prediction_config_id
  || reportSnapshot.value?.report_metadata?.prediction_config_id
  || reportSnapshot.value?.report_metadata?.evidence_package?.match?.prediction_config_id
  || reportSnapshot.value?.report_metadata?.evidence_package?.step2?.prediction_config?.prediction_config_id
))
const activeProjectId = computed(() => (
  props.projectId
  || predictionStatus.value?.project_id
  || resolveReportProjectId(reportSnapshot.value)
))
const isHistoricalReport = computed(() => {
  if (!reportSnapshot.value) return false
  return reportSnapshot.value.is_active_report === false
    || reportSnapshot.value.artifact_status === 'superseded'
    || reportSnapshot.value.report_metadata?.artifact_status === 'superseded'
})

const predictionMatchEventsCount = computed(() => {
  return predictionCounts.value.match_events ?? '-'
})

const predictionScenarioCasesCount = computed(() => {
  return predictionCounts.value.scenario_cases ?? '-'
})

const evidencePanel = computed(() => buildStep4ReportEvidence({
  reportSnapshot: reportSnapshot.value,
  predictionStatus: predictionStatus.value,
  reportOutline: reportOutline.value,
  generatedSections: generatedSections.value,
  workflowSteps: workflowSteps.value,
  statusText: statusText.value,
}))

const isTacticsSection = (section) => {
  return section?.title === '战术、阵型与预计首发'
}

const hasLineupWidget = computed(() => {
  const lineup = evidencePanel.value.widgets?.lineup || {}
  const home = Array.isArray(lineup.home?.players) ? lineup.home.players : []
  const away = Array.isArray(lineup.away?.players) ? lineup.away.players : []
  return home.length > 0 || away.length > 0
})

const formatElapsedTime = computed(() => {
  if (!startTime.value) return '0s'
  const lastLog = agentLogs.value[agentLogs.value.length - 1]
  const elapsed = lastLog?.elapsed_seconds || 0
  if (elapsed < 60) return `${Math.round(elapsed)}s`
  const mins = Math.floor(elapsed / 60)
  const secs = Math.round(elapsed % 60)
  return `${mins}m ${secs}s`
})

const displayLogs = computed(() => {
  return agentLogs.value
})

// Workflow steps overview (status-based, no nested cards)
const activeSectionIndex = computed(() => {
  if (isComplete.value) return null
  if (currentSectionIndex.value) return currentSectionIndex.value
  if (totalSections.value > 0 && completedSections.value < totalSections.value) return completedSections.value + 1
  return null
})

const isPlanningDone = computed(() => {
  return !!reportOutline.value?.sections?.length || agentLogs.value.some(l => l.action === 'planning_complete')
})

const isPlanningStarted = computed(() => {
  return agentLogs.value.some(l => l.action === 'planning_start' || l.action === 'report_start')
})

const isFinalizing = computed(() => {
  return !isComplete.value && !isFailed.value && isPlanningDone.value && totalSections.value > 0 && completedSections.value >= totalSections.value
})

// 当前活跃的步骤（用于顶部显示）
const activeStep = computed(() => {
  const steps = workflowSteps.value
  // 找到当前 active 的步骤
  const active = steps.find(s => s.status === 'active')
  if (active) return active
  
  // 如果没有 active，返回最后一个 done 的步骤
  const doneSteps = steps.filter(s => s.status === 'done')
  if (doneSteps.length > 0) return doneSteps[doneSteps.length - 1]
  
  // 否则返回第一个步骤
  return steps[0] || { noLabel: '--', title: '等待开始', status: 'todo', meta: '' }
})

const workflowSteps = computed(() => {
  const steps = []

  // Planning / Outline
  const planningStatus = isPlanningDone.value ? 'done' : (isPlanningStarted.value ? 'active' : 'todo')
  steps.push({
    key: 'planning',
    noLabel: 'PL',
    title: isFootballPredictionMode.value ? '证据组装 / 报告大纲' : 'Planning / Outline',
    status: planningStatus,
    meta: planningStatus === 'active' ? 'IN PROGRESS' : ''
  })

  // Sections (if outline exists)
  const sections = reportOutline.value?.sections || []
  sections.forEach((section, i) => {
    const idx = i + 1
    const status = (isComplete.value || !!generatedSections.value[idx])
      ? 'done'
      : (activeSectionIndex.value === idx ? 'active' : 'todo')

    steps.push({
      key: `section-${idx}`,
      noLabel: String(idx).padStart(2, '0'),
      title: section.title,
      status,
      meta: status === 'active' ? 'IN PROGRESS' : ''
    })
  })

  // Complete
  const completeStatus = isComplete.value ? 'done' : (isFinalizing.value ? 'active' : 'todo')
  steps.push({
    key: 'complete',
    noLabel: 'OK',
    title: isFootballPredictionMode.value ? '报告完成' : 'Complete',
    status: completeStatus,
    meta: completeStatus === 'active' ? 'FINALIZING' : ''
  })

  return steps
})

// Methods
const addLog = (msg) => {
  emit('add-log', msg)
}

const isSectionCompleted = (sectionIndex) => {
  return !!generatedSections.value[sectionIndex]
}

const formatTime = (timestamp) => {
  if (!timestamp) return ''
  try {
    return new Date(timestamp).toLocaleTimeString('en-US', { 
      hour12: false, 
      hour: '2-digit', 
      minute: '2-digit', 
      second: '2-digit' 
    })
  } catch {
    return ''
  }
}

const formatParams = (params) => {
  if (!params) return ''
  try {
    return JSON.stringify(params, null, 2)
  } catch {
    return String(params)
  }
}

const formatResultSize = (length) => {
  if (!length) return ''
  if (length < 1000) return `${length} chars`
  return `${(length / 1000).toFixed(1)}k chars`
}

const truncateText = (text, maxLen) => {
  if (!text) return ''
  if (text.length <= maxLen) return text
  return text.substring(0, maxLen) + '...'
}

const renderMarkdown = (content) => renderMarkdownHtml(content)

const getTimelineItemClass = (log, idx, total) => {
  const isLatest = idx === total - 1 && !isComplete.value
  const isMilestone = log.action === 'section_complete' || log.action === 'report_complete'
  return {
    'node--active': isLatest,
    'node--done': !isLatest && isMilestone,
    'node--muted': !isLatest && !isMilestone,
    'node--tool': log.action === 'tool_call' || log.action === 'tool_result'
  }
}

const getConnectorClass = (log, idx, total) => {
  const isLatest = idx === total - 1 && !isComplete.value
  if (isLatest) return 'dot-active'
  if (log.action === 'section_complete' || log.action === 'report_complete') return 'dot-done'
  return 'dot-muted'
}

const getActionLabel = (action) => {
  const labels = isFootballPredictionMode.value ? {
    'report_start': '预测报告开始',
    'planning_start': '证据组装',
    'planning_complete': '大纲完成',
    'section_start': '章节开始',
    'section_content': '内容就绪',
    'section_complete': '章节完成',
    'tool_call': '预测工具调用',
    'tool_result': '预测工具结果',
    'llm_response': '模型响应',
    'report_complete': '完成'
  } : {
    'report_start': 'Report Started',
    'planning_start': 'Planning',
    'planning_complete': 'Plan Complete',
    'section_start': 'Section Start',
    'section_content': 'Content Ready',
    'section_complete': 'Section Done',
    'tool_call': 'Tool Call',
    'tool_result': 'Tool Result',
    'llm_response': 'LLM Response',
    'report_complete': 'Complete'
  }
  return labels[action] || action
}

const refreshPredictionStatus = async () => {
  const runId = activePredictionRunId.value
  if (!isFootballPredictionMode.value || !runId) {
    predictionStatus.value = null
    return
  }

  try {
    const res = await getPredictionStatus(runId)
    predictionStatus.value = res.data || null
  } catch (err) {
    console.warn('Failed to fetch prediction status:', err)
  }
}

const getLogLevelClass = (log) => {
  if (log.includes('ERROR') || log.includes('错误')) return 'error'
  if (log.includes('WARNING') || log.includes('警告')) return 'warning'
  // INFO 使用默认颜色，不标记为 success
  return ''
}

// Polling
let agentLogTimer = null
let consoleLogTimer = null

const fetchAgentLog = async () => {
  if (!props.reportId) return
  
  try {
    const res = await getAgentLog(props.reportId, agentLogLine.value)
    
    if (res.success && res.data) {
      const newLogs = res.data.logs || []
      
      if (newLogs.length > 0) {
        newLogs.forEach(log => {
          agentLogs.value.push(log)
          
          if (log.action === 'planning_complete' && log.details?.outline) {
            reportOutline.value = log.details.outline
          }
          
          if (log.action === 'section_start') {
            currentSectionIndex.value = log.section_index
          }

          // section_complete - 章节生成完成
          if (log.action === 'section_complete') {
            if (log.details?.content) {
              generatedSections.value[log.section_index] = log.details.content
              // 自动展开刚生成的章节
              expandedContent.value.add(log.section_index - 1)
              currentSectionIndex.value = null
            }
          }
          
          if (log.action === 'report_complete') {
            markReportCompleted()
            // 滚动逻辑统一在循环结束后的 nextTick 中处理
          }
          
          if (log.action === 'report_start') {
            startTime.value = new Date(log.timestamp)
          }
        })
        
        agentLogLine.value = res.data.from_line + newLogs.length
        
        nextTick(() => {
          if (rightPanel.value) {
            // 如果任务已完成，滚动到顶部；否则滚动到底部跟随最新日志
            if (isComplete.value) {
              rightPanel.value.scrollTop = 0
            } else {
              rightPanel.value.scrollTop = rightPanel.value.scrollHeight
            }
          }
        })
      }
    }
  } catch (err) {
    console.warn('Failed to fetch agent log:', err)
  }
}

// 提取最终答案内容 - 从 LLM response 中提取章节内容
const extractFinalContent = (response) => {
  if (!response) return null
  
  // 尝试提取 <final_answer> 标签内的内容
  const finalAnswerTagMatch = response.match(/<final_answer>([\s\S]*?)<\/final_answer>/)
  if (finalAnswerTagMatch) {
    return finalAnswerTagMatch[1].trim()
  }
  
  // 尝试找 Final Answer: 后面的内容（支持多种格式）
  // 格式1: Final Answer:\n\n内容
  // 格式2: Final Answer: 内容
  const finalAnswerMatch = response.match(/Final\s*Answer:\s*\n*([\s\S]*)$/i)
  if (finalAnswerMatch) {
    return finalAnswerMatch[1].trim()
  }
  
  // 尝试找 最终答案: 后面的内容
  const chineseFinalMatch = response.match(/最终答案[:：]\s*\n*([\s\S]*)$/i)
  if (chineseFinalMatch) {
    return chineseFinalMatch[1].trim()
  }
  
  // 如果以 ## 或 # 或 > 开头，可能是直接的 markdown 内容
  const trimmedResponse = response.trim()
  if (trimmedResponse.match(/^[#>]/)) {
    return trimmedResponse
  }
  
  // 如果内容较长且包含markdown格式，尝试移除思考过程后返回
  if (response.length > 300 && (response.includes('**') || response.includes('>'))) {
    // 移除 Thought: 开头的思考过程
    const thoughtMatch = response.match(/^Thought:[\s\S]*?(?=\n\n[^T]|\n\n$)/i)
    if (thoughtMatch) {
      const afterThought = response.substring(thoughtMatch[0].length).trim()
      if (afterThought.length > 100) {
        return afterThought
      }
    }
  }
  
  return null
}

const fetchConsoleLog = async () => {
  if (!props.reportId) return
  
  try {
    const res = await getConsoleLog(props.reportId, consoleLogLine.value)
    
    if (res.success && res.data) {
      const newLogs = res.data.logs || []
      
      if (newLogs.length > 0) {
        consoleLogs.value.push(...newLogs)
        consoleLogLine.value = res.data.from_line + newLogs.length
        
        nextTick(() => {
          if (logContent.value) {
            logContent.value.scrollTop = logContent.value.scrollHeight
          }
        })
      }
    }
  } catch (err) {
    console.warn('Failed to fetch console log:', err)
  }
}

const applyGeneratedSections = (sections = []) => {
  const expanded = new Set(expandedContent.value)
  sections.forEach(section => {
    if (!section?.section_index) return
    generatedSections.value[section.section_index] = section.content || ''
    expanded.add(section.section_index - 1)
  })
  expandedContent.value = expanded
}

const markReportCompleted = () => {
  reportStatus.value = 'completed'
  isComplete.value = true
  isFailed.value = false
  currentSectionIndex.value = null
  emit('update-status', 'completed')
  stopPolling()
}

const markReportFailed = () => {
  reportStatus.value = 'failed'
  isComplete.value = false
  isFailed.value = true
  currentSectionIndex.value = null
  emit('update-status', 'error')
  stopPolling()
}

const isTerminalReport = () => isComplete.value || isFailed.value

const refreshReportSnapshot = async () => {
  if (!props.reportId) return false

  let terminal = false

  try {
    const reportRes = await getReport(props.reportId)
    if (reportRes.success && reportRes.data) {
      const report = reportRes.data
      reportSnapshot.value = report
      reportStatus.value = report.status || 'pending'
      if (report.outline) {
        reportOutline.value = report.outline
      }
      if (report.created_at && !startTime.value) {
        startTime.value = new Date(report.created_at)
      }
      if (report.status === 'completed') {
        markReportCompleted()
        terminal = true
      } else if (report.status === 'failed') {
        markReportFailed()
        terminal = true
      } else {
        emit('update-status', 'processing')
      }
    }
  } catch (err) {
    console.warn('Failed to fetch report snapshot:', err)
  }

  try {
    const sectionsRes = await getReportSections(props.reportId)
    if (sectionsRes.success && sectionsRes.data) {
      applyGeneratedSections(sectionsRes.data.sections || [])
      if (sectionsRes.data.is_complete && !isFailed.value) {
        markReportCompleted()
        terminal = true
      }
    }
  } catch (err) {
    console.warn('Failed to fetch report sections:', err)
  }

  if (!isTerminalReport() && reportOutline.value?.sections?.length) {
    const nextSection = Object.keys(generatedSections.value).length + 1
    if (nextSection <= reportOutline.value.sections.length) {
      currentSectionIndex.value = nextSection
    }
  }

  return terminal || isTerminalReport()
}

const resetReportState = () => {
  stopPolling()
  agentLogs.value = []
  consoleLogs.value = []
  agentLogLine.value = 0
  consoleLogLine.value = 0
  reportOutline.value = null
  reportSnapshot.value = null
  currentSectionIndex.value = null
  generatedSections.value = {}
  expandedContent.value = new Set()
  expandedLogs.value = new Set()
  collapsedSections.value = new Set()
  isComplete.value = false
  isFailed.value = false
  reportStatus.value = 'pending'
  startTime.value = null
  predictionStatus.value = null
}

const regenerateStep4Report = async () => {
  if (!activeProjectId.value || !activePredictionRunId.value || isRegeneratingReport.value) return
  isRegeneratingReport.value = true
  try {
    const regenerated = await regenerateStepWithConfirm({
      projectId: activeProjectId.value,
      step: 4,
      reason: 'step4_report_regenerate',
      onBefore: () => {
        resetReportState()
        emit('update-status', 'processing')
        addLog('Step4 报告重新生成，旧 Step5 问答已失效')
      },
    })
    if (!regenerated) return
    const response = await createPredictionReportForProject(activeProjectId.value, {
      force_regenerate: true,
      prediction_run_id: activePredictionRunId.value,
      prediction_config_id: activePredictionConfigId.value,
    })
    const newReportId = response.data?.report_id
    if (newReportId) {
      addLog(`新赛事预测报告已生成: ${newReportId}`)
      router.replace({ name: 'Report', params: { reportId: newReportId } })
    }
  } catch (err) {
    markReportFailed()
    addLog(`重新生成报告失败: ${err.message}`)
  } finally {
    isRegeneratingReport.value = false
  }
}

let reportLoadToken = 0

const initializeReport = async (reportId) => {
  if (!reportId) return

  const loadToken = ++reportLoadToken
  resetReportState()
  addLog(`Prediction report initialized: ${reportId}`)

  await refreshPredictionStatus()
  const terminal = await refreshReportSnapshot()
  if (loadToken !== reportLoadToken) return

  await fetchAgentLog()
  await fetchConsoleLog()
  if (loadToken !== reportLoadToken) return

  if (!terminal && !isTerminalReport()) {
    startPolling({ fetchImmediately: false })
  }
}

const startPolling = ({ fetchImmediately = true } = {}) => {
  if (agentLogTimer || consoleLogTimer) return

  if (fetchImmediately) {
    fetchAgentLog()
    fetchConsoleLog()
  }
  
  agentLogTimer = setInterval(fetchAgentLog, 2000)
  consoleLogTimer = setInterval(fetchConsoleLog, 1500)
}

const stopPolling = () => {
  if (agentLogTimer) {
    clearInterval(agentLogTimer)
    agentLogTimer = null
  }
  if (consoleLogTimer) {
    clearInterval(consoleLogTimer)
    consoleLogTimer = null
  }
}

// Lifecycle
onMounted(() => {
  if (props.reportId) addLog(`Report view mounted: ${props.reportId}`)
})

onUnmounted(() => {
  stopPolling()
})

watch(() => props.reportId, (newId) => {
  if (newId) {
    initializeReport(newId)
  } else {
    resetReportState()
  }
}, { immediate: true })

watch(
  () => [props.isFootballPrediction, props.predictionRunId, props.simulationId, props.predictionConfigId],
  () => {
    refreshPredictionStatus()
  }
)
</script>

<style scoped>
.report-panel {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: #F8F9FA;
  font-family: 'Inter', 'Noto Sans SC', system-ui, sans-serif;
  overflow: hidden;
}

/* Main Split Layout */
.main-split-layout {
  flex: 1;
  display: flex;
  overflow: hidden;
}

/* Panel Headers */
.panel-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 20px;
  background: #FFFFFF;
  border-bottom: 1px solid #E5E7EB;
  font-size: 13px;
  font-weight: 600;
  color: #374151;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  position: sticky;
  top: 0;
  z-index: 10;
}

.header-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #1F2937;
  box-shadow: 0 0 0 3px rgba(31, 41, 55, 0.15);
  margin-right: 10px;
  flex-shrink: 0;
  animation: pulse-dot 1.5s ease-in-out infinite;
}

@keyframes pulse-dot {
  0%, 100% {
    box-shadow: 0 0 0 3px rgba(31, 41, 55, 0.15);
  }
  50% {
    box-shadow: 0 0 0 5px rgba(31, 41, 55, 0.1);
  }
}

.header-index {
  font-size: 12px;
  font-weight: 600;
  color: #9CA3AF;
  margin-right: 10px;
  flex-shrink: 0;
}

.header-title {
  font-size: 13px;
  font-weight: 600;
  color: #374151;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  text-transform: none;
  letter-spacing: 0;
}

.header-meta {
  margin-left: auto;
  font-size: 10px;
  font-weight: 600;
  color: #6B7280;
  flex-shrink: 0;
}

/* Panel header status variants */
.panel-header--active {
  background: #FAFAFA;
  border-color: #1F2937;
}

.panel-header--active .header-index {
  color: #1F2937;
}

.panel-header--active .header-title {
  color: #1F2937;
}

.panel-header--active .header-meta {
  color: #1F2937;
}

.panel-header--done {
  background: #F9FAFB;
}

.panel-header--done .header-index {
  color: #10B981;
}

.panel-header--todo .header-index,
.panel-header--todo .header-title {
  color: #9CA3AF;
}

/* Left Panel - Report Style */
.left-panel.report-style {
  width: 45%;
  min-width: 450px;
  background: #FFFFFF;
  border-right: 1px solid #E5E7EB;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  padding: 30px 50px 60px 50px;
}

.left-panel::-webkit-scrollbar {
  width: 6px;
}

.left-panel::-webkit-scrollbar-track {
  background: transparent;
}

.left-panel::-webkit-scrollbar-thumb {
  background: transparent;
  border-radius: 3px;
  transition: background 0.3s ease;
}

.left-panel:hover::-webkit-scrollbar-thumb {
  background: rgba(0, 0, 0, 0.15);
}

.left-panel::-webkit-scrollbar-thumb:hover {
  background: rgba(0, 0, 0, 0.25);
}

/* Report Header */
.report-content-wrapper {
  max-width: 800px;
  margin: 0 auto;
  width: 100%;
}

.report-header-block {
  margin-bottom: 30px;
}

.report-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 24px;
}

.report-tag {
  background: #000000;
  color: #FFFFFF;
  font-size: 11px;
  font-weight: 700;
  padding: 4px 8px;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}

.report-id {
  font-size: 11px;
  color: #9CA3AF;
  font-weight: 500;
  letter-spacing: 0.02em;
}

.main-title {
  font-family: 'Times New Roman', Times, serif;
  font-size: 36px;
  font-weight: 700;
  color: #111827;
  line-height: 1.2;
  margin: 0 0 16px 0;
  letter-spacing: -0.02em;
}

.sub-title {
  font-family: 'Times New Roman', Times, serif;
  font-size: 16px;
  color: #6B7280;
  font-style: italic;
  line-height: 1.6;
  margin: 0 0 30px 0;
  font-weight: 400;
}

.header-divider {
  height: 1px;
  background: #E5E7EB;
  width: 100%;
}

/* Sections List */
.sections-list {
  display: flex;
  flex-direction: column;
  gap: 32px;
}

.report-section-item {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.section-header-row {
  display: flex;
  align-items: baseline;
  gap: 12px;
  transition: background-color 0.2s ease;
  padding: 8px 12px;
  margin: -8px -12px;
  border-radius: 8px;
}

.section-header-row.clickable {
  cursor: pointer;
}

.section-header-row.clickable:hover {
  background-color: #F9FAFB;
}

.collapse-icon {
  margin-left: auto;
  color: #9CA3AF;
  transition: transform 0.3s ease;
  flex-shrink: 0;
  align-self: center;
}

.collapse-icon.is-collapsed {
  transform: rotate(-90deg);
}

.section-number {
  font-family: 'JetBrains Mono', monospace;
  font-size: 16px;
  color: #9CA3AF; /* 深灰色，不随状态变化 */
  font-weight: 500;
}

.section-title {
  font-family: 'Times New Roman', Times, serif;
  font-size: 24px;
  font-weight: 600;
  color: #111827;
  margin: 0;
  transition: color 0.3s ease;
}

/* States */
.report-section-item.is-pending .section-title {
  color: #D1D5DB;
}

.report-section-item.is-active .section-title,
.report-section-item.is-completed .section-title {
  color: #111827;
}

.section-body {
  padding-left: 28px;
  overflow: hidden;
}

.structured-report-widgets {
  margin: 6px 0 20px;
}

.lineup-widget-empty {
  padding: 16px;
  margin: 14px 0;
  border: 1px dashed #CBD5CF;
  border-radius: 6px;
  background: #F7F8F6;
  color: #68756E;
  font-size: 13px;
}

/* Generated Content */
.generated-content {
  font-family: 'Inter', 'Noto Sans SC', system-ui, sans-serif;
  font-size: 14px;
  line-height: 1.8;
  color: #374151;
}

.generated-content :deep(p) {
  margin-bottom: 1em;
}

.generated-content :deep(.md-h2),
.generated-content :deep(.md-h3),
.generated-content :deep(.md-h4) {
  font-family: 'Times New Roman', Times, serif;
  color: #111827;
  margin-top: 1.5em;
  margin-bottom: 0.8em;
  font-weight: 700;
}

.generated-content :deep(.md-h2) { font-size: 20px; border-bottom: 1px solid #F3F4F6; padding-bottom: 8px; }
.generated-content :deep(.md-h3) { font-size: 18px; }
.generated-content :deep(.md-h4) { font-size: 16px; }

.generated-content :deep(.md-ul),
.generated-content :deep(.md-ol) {
  padding-left: 24px;
  margin: 12px 0;
}

.generated-content :deep(.md-li),
.generated-content :deep(.md-oli) {
  margin: 6px 0;
}

.generated-content :deep(.md-quote) {
  border-left: 3px solid #E5E7EB;
  padding-left: 16px;
  margin: 1.5em 0;
  color: #6B7280;
  font-style: italic;
  font-family: 'Times New Roman', Times, serif;
}

.generated-content :deep(.code-block) {
  background: #F9FAFB;
  padding: 12px;
  border-radius: 6px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  overflow-x: auto;
  margin: 1em 0;
  border: 1px solid #E5E7EB;
}

.generated-content :deep(.md-table-wrap) {
  width: 100%;
  overflow-x: auto;
  margin: 14px 0 18px;
  border: 1px solid #E5E7EB;
  border-radius: 8px;
}

.generated-content :deep(.md-table) {
  width: 100%;
  min-width: 520px;
  border-collapse: collapse;
  font-size: 13px;
  line-height: 1.55;
  background: #FFFFFF;
}

.generated-content :deep(.md-table th) {
  background: #F9FAFB;
  color: #374151;
  font-weight: 700;
  text-align: left;
  padding: 9px 11px;
  border-bottom: 1px solid #E5E7EB;
  white-space: nowrap;
}

.generated-content :deep(.md-table td) {
  color: #4B5563;
  padding: 9px 11px;
  border-top: 1px solid #F3F4F6;
  vertical-align: top;
}

.generated-content :deep(.md-table tr:first-child td) {
  border-top: none;
}

.generated-content :deep(strong) {
  font-weight: 600;
  color: #111827;
}

/* Loading State */
.loading-state {
  display: flex;
  align-items: center;
  gap: 10px;
  color: #6B7280;
  font-size: 14px;
  margin-top: 4px;
}

.loading-icon {
  width: 18px;
  height: 18px;
  animation: spin 1s linear infinite;
  display: flex;
  align-items: center;
  justify-content: center;
}

.loading-text {
  font-family: 'Times New Roman', Times, serif;
  font-size: 15px;
  color: #4B5563;
}

.cursor-blink {
  display: inline-block;
  width: 8px;
  height: 14px;
  background: #8B5CF6;
  opacity: 0.5;
  animation: blink 1s step-end infinite;
}

@keyframes blink {
  0%, 100% { opacity: 0.5; }
  50% { opacity: 0; }
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* Content Styles Override for this view */
.generated-content :deep(.md-h2) {
  font-family: 'Times New Roman', Times, serif;
  font-size: 18px;
  margin-top: 0;
}


/* Slide Content Transition */
.slide-content-enter-active {
  transition: opacity 0.3s ease-out;
}

.slide-content-leave-active {
  transition: opacity 0.2s ease-in;
}

.slide-content-enter-from,
.slide-content-leave-to {
  opacity: 0;
}

.slide-content-enter-to,
.slide-content-leave-from {
  opacity: 1;
}

/* Waiting Placeholder */
.waiting-placeholder {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 20px;
  padding: 40px;
  color: #9CA3AF;
}

.waiting-animation {
  position: relative;
  width: 48px;
  height: 48px;
}

.waiting-ring {
  position: absolute;
  width: 100%;
  height: 100%;
  border: 2px solid #E5E7EB;
  border-radius: 50%;
  animation: ripple 2s cubic-bezier(0.4, 0, 0.2, 1) infinite;
}

.waiting-ring:nth-child(2) {
  animation-delay: 0.4s;
}

.waiting-ring:nth-child(3) {
  animation-delay: 0.8s;
}

@keyframes ripple {
  0% { transform: scale(0.5); opacity: 1; }
  100% { transform: scale(2); opacity: 0; }
}

.waiting-text {
  font-size: 14px;
}

/* Right Panel */
.right-panel {
  flex: 1;
  background: #FFFFFF;
  overflow-y: auto;
  display: flex;
  flex-direction: column;

  /* Functional palette (low saturation, status-based) */
  --wf-border: #E5E7EB;
  --wf-divider: #F3F4F6;

  --wf-active-bg: #FAFAFA;
  --wf-active-border: #1F2937;
  --wf-active-dot: #1F2937;
  --wf-active-text: #1F2937;

  --wf-done-bg: #F9FAFB;
  --wf-done-border: #E5E7EB;
  --wf-done-dot: #10B981;

  --wf-muted-dot: #D1D5DB;
  --wf-todo-text: #9CA3AF;
}

.right-panel::-webkit-scrollbar {
  width: 6px;
}

.right-panel::-webkit-scrollbar-track {
  background: transparent;
}

.right-panel::-webkit-scrollbar-thumb {
  background: transparent;
  border-radius: 3px;
  transition: background 0.3s ease;
}

.right-panel:hover::-webkit-scrollbar-thumb {
  background: rgba(0, 0, 0, 0.15);
}

.right-panel::-webkit-scrollbar-thumb:hover {
  background: rgba(0, 0, 0, 0.25);
}

.mono {
  font-family: 'JetBrains Mono', monospace;
}

/* Workflow Overview */
.workflow-overview {
  padding: 16px 20px 0 20px;
}

.evidence-overview {
  border-bottom: 1px solid var(--wf-divider);
}

.evidence-status-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.evidence-kicker {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.match-verdict {
  border: 1px solid var(--wf-border);
  border-radius: 8px;
  padding: 12px 14px;
  margin-bottom: 12px;
  background: #FAFAFA;
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.match-verdict .match-eyebrow {
  font-size: 11px;
  font-weight: 700;
  color: #6B7280;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.match-verdict strong {
  font-family: 'Times New Roman', Times, serif;
  font-size: 24px;
  line-height: 1.2;
  color: #111827;
}

.match-verdict span:last-child {
  font-size: 12px;
  color: #4B5563;
}

.historical-report-notice {
  margin: -2px 0 12px;
  padding: 10px 12px;
  border: 1px solid #F1D7A6;
  border-radius: 6px;
  background: #FFF8E8;
  color: #7A4F10;
  font-size: 12px;
  line-height: 1.55;
}

.evidence-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin-bottom: 12px;
}

.evidence-cell {
  min-width: 0;
  padding: 9px 10px;
  border: 1px solid var(--wf-divider);
  border-radius: 8px;
  background: #FFFFFF;
}

.evidence-cell span,
.credibility-item span,
.evidence-stat span {
  display: block;
  font-size: 11px;
  font-weight: 600;
  color: #9CA3AF;
  letter-spacing: 0.02em;
}

.evidence-cell strong {
  display: block;
  margin-top: 4px;
  font-size: 12px;
  color: #1F2937;
  line-height: 1.35;
  overflow-wrap: anywhere;
}

.evidence-stats {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 1px;
  margin-bottom: 12px;
  border: 1px solid var(--wf-divider);
  border-radius: 8px;
  overflow: hidden;
  background: var(--wf-divider);
}

.evidence-stat {
  min-width: 0;
  padding: 9px 8px;
  background: #FFFFFF;
}

.evidence-stat strong {
  display: block;
  font-size: 13px;
  color: #111827;
  margin-bottom: 2px;
}

.credibility-strip {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  margin-bottom: 14px;
}

.credibility-item {
  min-width: 0;
  padding: 9px 10px;
  border: 1px solid var(--wf-divider);
  border-radius: 8px;
  background: #FFFFFF;
}

.credibility-item strong {
  display: block;
  margin-top: 4px;
  font-size: 12px;
  color: #1F2937;
  line-height: 1.35;
  overflow-wrap: anywhere;
}

.credibility-item--warn {
  background: #FFFBEB;
  border-color: #FDE68A;
}

.credibility-item--warn strong {
  color: #92400E;
}

.evidence-tabs {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 4px;
  padding: 4px;
  margin-bottom: 12px;
  border: 1px solid var(--wf-divider);
  border-radius: 8px;
  background: #F9FAFB;
}

.evidence-tab {
  min-width: 0;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: #6B7280;
  padding: 7px 4px;
  cursor: pointer;
  text-align: center;
  transition: background-color 0.15s ease, color 0.15s ease;
}

.evidence-tab span,
.evidence-tab small {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.evidence-tab span {
  font-size: 12px;
  font-weight: 700;
  line-height: 1.2;
}

.evidence-tab small {
  margin-top: 2px;
  font-size: 10px;
  color: #9CA3AF;
}

.evidence-tab:hover,
.evidence-tab.is-active {
  background: #FFFFFF;
  color: #111827;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.08);
}

.evidence-tab.is-active small {
  color: #4B5563;
}

.evidence-insight-panel {
  margin-bottom: 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.insight-section {
  border: 1px solid var(--wf-divider);
  border-radius: 8px;
  background: #FFFFFF;
  padding: 10px;
}

.insight-section-title {
  margin-bottom: 8px;
  font-size: 11px;
  font-weight: 800;
  color: #6B7280;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.probability-list,
.team-compare-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.probability-row {
  display: grid;
  grid-template-columns: minmax(72px, 0.8fr) minmax(90px, 1fr) auto;
  gap: 8px;
  align-items: center;
}

.probability-label {
  min-width: 0;
}

.probability-label span {
  display: block;
  font-size: 10px;
  font-weight: 700;
  color: #9CA3AF;
}

.probability-label strong {
  display: block;
  margin-top: 1px;
  font-size: 12px;
  line-height: 1.2;
  color: #1F2937;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.probability-track {
  height: 8px;
  border-radius: 999px;
  background: #F3F4F6;
  overflow: hidden;
}

.probability-fill {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: #111827;
}

.probability-value {
  display: none;
}

.probability-percent {
  min-width: 42px;
  font-size: 11px;
  font-weight: 700;
  color: #374151;
  text-align: right;
}

.source-mini-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.source-mini-cell {
  min-width: 0;
  padding: 8px;
  border: 1px solid var(--wf-divider);
  border-radius: 6px;
  background: #FAFAFA;
}

.source-mini-cell span,
.source-mini-cell small {
  display: block;
  font-size: 10px;
  font-weight: 700;
  color: #9CA3AF;
}

.source-mini-cell strong {
  display: block;
  margin: 4px 0 2px;
  font-size: 12px;
  line-height: 1.3;
  color: #111827;
  overflow-wrap: anywhere;
}

.team-compare-row,
.score-candidate,
.scenario-row,
.player-row,
.coach-note-row,
.event-bucket,
.event-item,
.risk-row {
  width: 100%;
  min-width: 0;
  border: 1px solid var(--wf-divider);
  border-radius: 7px;
  background: #FFFFFF;
  color: inherit;
  cursor: pointer;
  text-align: left;
}

.team-compare-row:not(button) {
  cursor: default;
}

button.team-compare-row:hover,
.score-candidate:hover,
.scenario-row:hover,
.player-row:hover,
.coach-note-row:hover,
.event-bucket:hover,
.event-item:hover,
.risk-row:hover,
.wf-step:hover {
  border-color: var(--wf-border);
  background: #F9FAFB;
}

.team-compare-row {
  padding: 9px;
}

.team-compare-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
}

.team-compare-head strong {
  min-width: 0;
  font-size: 13px;
  color: #111827;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.team-compare-head span {
  flex-shrink: 0;
  font-size: 11px;
  font-weight: 700;
  color: #4B5563;
}

.team-compare-metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 4px;
  margin-top: 7px;
}

.team-compare-metrics span {
  min-width: 0;
  padding: 4px 5px;
  border-radius: 4px;
  background: #F9FAFB;
  font-size: 10px;
  font-weight: 700;
  color: #4B5563;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.team-compare-row small {
  display: block;
  margin-top: 7px;
  font-size: 11px;
  line-height: 1.35;
  color: #6B7280;
}

.score-candidate,
.scenario-row,
.event-bucket,
.risk-row {
  display: grid;
  grid-template-columns: auto 1fr auto;
  gap: 8px;
  align-items: center;
  padding: 8px;
  margin-bottom: 6px;
}

.score-candidate:last-child,
.scenario-row:last-child,
.event-bucket:last-child,
.risk-row:last-child,
.player-row:last-child,
.coach-note-row:last-child,
.event-item:last-child {
  margin-bottom: 0;
}

.score-rank {
  font-size: 10px;
  font-weight: 800;
  color: #9CA3AF;
}

.score-candidate strong {
  font-size: 18px;
  color: #111827;
}

.score-context,
.scenario-row span,
.event-bucket span {
  min-width: 0;
  font-size: 11px;
  color: #6B7280;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.score-prob,
.scenario-row small,
.event-bucket small {
  font-size: 11px;
  font-weight: 700;
  color: #374151;
}

.scenario-row {
  grid-template-columns: minmax(78px, 0.8fr) minmax(0, 1fr) auto;
}

.scenario-row strong,
.event-bucket strong {
  min-width: 0;
  font-size: 12px;
  color: #111827;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.player-row,
.coach-note-row {
  display: grid;
  grid-template-columns: minmax(56px, 0.5fr) minmax(80px, 0.9fr) minmax(0, 1fr);
  gap: 8px;
  align-items: center;
  padding: 8px;
  margin-bottom: 6px;
}

.player-row span,
.player-row small,
.coach-note-row span,
.coach-note-row small {
  min-width: 0;
  font-size: 11px;
  color: #6B7280;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.player-row strong,
.coach-note-row strong {
  min-width: 0;
  font-size: 12px;
  color: #111827;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.coach-note-row {
  grid-template-columns: minmax(64px, 0.6fr) minmax(0, 1fr) auto;
}

.lineup-widget-jump {
  width: 100%;
  border: 1px solid #D8E2DB;
  background:
    linear-gradient(90deg, rgba(242, 139, 46, 0.12), rgba(40, 123, 216, 0.12)),
    #F7FAF7;
  border-radius: 8px;
  padding: 12px;
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  gap: 8px;
  align-items: center;
  color: #17231C;
  cursor: pointer;
  text-align: center;
}

.lineup-widget-jump strong {
  min-width: 0;
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.lineup-widget-jump span {
  color: #6B756E;
  font-size: 11px;
  font-weight: 900;
}

.lineup-widget-jump small {
  grid-column: 1 / -1;
  color: #657168;
  font-size: 11px;
}

.event-item {
  display: grid;
  grid-template-columns: 36px minmax(54px, 0.5fr) minmax(0, 1fr);
  gap: 8px;
  align-items: baseline;
  padding: 8px;
  margin-bottom: 6px;
}

.event-item span,
.event-item small {
  font-size: 11px;
  color: #6B7280;
}

.event-item strong {
  font-size: 12px;
  color: #111827;
}

.event-item em {
  grid-column: 1 / -1;
  font-style: normal;
  font-size: 11px;
  line-height: 1.4;
  color: #4B5563;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.risk-row {
  grid-template-columns: minmax(56px, 0.55fr) minmax(0, 1fr);
  align-items: start;
}

.risk-row span {
  font-size: 12px;
  font-weight: 800;
  color: #374151;
}

.risk-row strong {
  min-width: 0;
  font-size: 12px;
  color: #111827;
  overflow-wrap: anywhere;
}

.risk-row small {
  grid-column: 2;
  margin-top: -2px;
  font-size: 11px;
  line-height: 1.35;
  color: #6B7280;
}

.risk-row--warn {
  background: #FFFBEB;
  border-color: #FDE68A;
}

.risk-row--warn span,
.risk-row--warn strong {
  color: #92400E;
}

.insight-empty {
  padding: 10px;
  border: 1px dashed var(--wf-border);
  border-radius: 7px;
  background: #FAFAFA;
  font-size: 12px;
  color: #9CA3AF;
  text-align: center;
}

.workflow-metrics {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}

.metric {
  display: inline-flex;
  align-items: baseline;
  gap: 6px;
}

.metric-right {
  margin-left: auto;
}

.metric-label {
  font-size: 11px;
  font-weight: 600;
  color: #9CA3AF;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.metric-value {
  font-size: 12px;
  color: #374151;
}

.metric-pill {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px solid var(--wf-border);
  background: #F9FAFB;
  color: #6B7280;
}

.metric-pill.pill--processing {
  background: var(--wf-active-bg);
  border-color: var(--wf-active-border);
  color: var(--wf-active-text);
}

.metric-pill.pill--completed {
  background: #ECFDF5;
  border-color: #A7F3D0;
  color: #065F46;
}

.metric-pill.pill--pending {
  background: transparent;
  border-style: dashed;
  color: #6B7280;
}

.workflow-steps {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding-bottom: 10px;
}

.evidence-steps {
  margin-top: 2px;
}

.wf-step {
  display: grid;
  grid-template-columns: 24px 1fr;
  gap: 12px;
  padding: 10px 12px;
  border: 1px solid var(--wf-divider);
  border-radius: 8px;
  background: #FFFFFF;
}

.wf-step--active {
  background: var(--wf-active-bg);
  border-color: var(--wf-active-border);
}

.wf-step--done {
  background: var(--wf-done-bg);
  border-color: var(--wf-done-border);
}

.wf-step--todo {
  background: transparent;
  border-color: var(--wf-border);
  border-style: dashed;
}

.wf-step-connector {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 24px;
  flex-shrink: 0;
}

.wf-step-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--wf-muted-dot);
  border: 2px solid #FFFFFF;
  z-index: 1;
}

.wf-step-line {
  width: 2px;
  flex: 1;
  background: var(--wf-divider);
  margin-top: -2px;
}

.wf-step--active .wf-step-dot {
  background: var(--wf-active-dot);
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.12);
}

.wf-step--done .wf-step-dot {
  background: var(--wf-done-dot);
}

.wf-step-title-row {
  display: flex;
  align-items: baseline;
  gap: 10px;
  min-width: 0;
}

.wf-step-index {
  font-size: 11px;
  font-weight: 700;
  color: #9CA3AF;
  letter-spacing: 0.02em;
  flex-shrink: 0;
}

.wf-step-title {
  font-family: 'Times New Roman', Times, serif;
  font-size: 13px;
  font-weight: 600;
  color: #111827;
  line-height: 1.35;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.wf-step-hint {
  margin-top: 4px;
  font-size: 11px;
  line-height: 1.45;
  color: #6B7280;
}

.wf-step--todo .wf-step-hint {
  color: #A1A1AA;
}

.wf-step-meta {
  margin-left: auto;
  font-size: 10px;
  font-weight: 700;
  color: var(--wf-active-text);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  flex-shrink: 0;
}

.wf-step--todo .wf-step-title,
.wf-step--todo .wf-step-index {
  color: var(--wf-todo-text);
}

.workflow-divider {
  height: 1px;
  background: var(--wf-divider);
  margin: 14px 0 0 0;
}

/* Workflow Timeline */
.workflow-timeline {
  padding: 14px 20px 24px;
  flex: 1;
}

.timeline-item {
  display: grid;
  grid-template-columns: 24px 1fr;
  gap: 12px;
  padding: 10px 12px;
  margin-bottom: 10px;
  border: 1px solid var(--wf-divider);
  border-radius: 8px;
  background: #FFFFFF;
  transition: background-color 0.15s ease, border-color 0.15s ease;
}

.timeline-item:hover {
  background: #F9FAFB;
  border-color: var(--wf-border);
}

.timeline-item.node--active {
  background: var(--wf-active-bg);
  border-color: var(--wf-active-border);
}

.timeline-item.node--active:hover {
  background: var(--wf-active-bg);
  border-color: var(--wf-active-border);
}

.timeline-item.node--done {
  background: var(--wf-done-bg);
  border-color: var(--wf-done-border);
}

.timeline-item.node--done:hover {
  background: var(--wf-done-bg);
  border-color: var(--wf-done-border);
}

.timeline-connector {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 24px;
  flex-shrink: 0;
}

.connector-dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: var(--wf-muted-dot);
  border: 2px solid #FFFFFF;
  z-index: 1;
}

.connector-line {
  width: 2px;
  flex: 1;
  background: var(--wf-divider);
  margin-top: -2px;
}

/* Connector dot: status only */
.dot-active {
  background: var(--wf-active-dot);
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.12);
}

.dot-done {
  background: var(--wf-done-dot);
}

.dot-muted {
  background: var(--wf-muted-dot);
}

.timeline-content {
  min-width: 0;
  background: transparent;
  border: none;
  border-radius: 0;
  padding: 0;
  margin: 0;
  transition: none;
}

.timeline-content:hover {
  box-shadow: none;
}

.timeline-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}

.action-label {
  font-size: 12px;
  font-weight: 600;
  color: #374151;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}

.action-time {
  font-size: 11px;
  color: #9CA3AF;
  font-family: 'JetBrains Mono', monospace;
}

.timeline-body {
  font-size: 13px;
  color: #4B5563;
}

.timeline-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid #F3F4F6;
}

.elapsed-placeholder {
  flex-shrink: 0;
}

.footer-actions {
  display: flex;
  gap: 8px;
  margin-left: auto;
}

.elapsed-badge {
  font-size: 11px;
  color: #6B7280;
  background: #F3F4F6;
  padding: 2px 8px;
  border-radius: 10px;
  font-family: 'JetBrains Mono', monospace;
}

/* Timeline Body Elements */
.info-row {
  display: flex;
  gap: 8px;
  margin-bottom: 6px;
}

.info-key {
  font-size: 11px;
  color: #9CA3AF;
  min-width: 80px;
}

.info-val {
  color: #374151;
}

.status-message {
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 13px;
  border: 1px solid transparent;
}

.status-message.planning {
  background: var(--wf-active-bg);
  border-color: var(--wf-active-border);
  color: var(--wf-active-text);
}

.status-message.success {
  background: #ECFDF5;
  border-color: #A7F3D0;
  color: #065F46;
}

.outline-badge {
  display: inline-block;
  margin-top: 8px;
  padding: 4px 10px;
  background: #F9FAFB;
  color: #6B7280;
  border: 1px solid #E5E7EB;
  border-radius: 12px;
  font-size: 11px;
  font-weight: 500;
}

.section-tag {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  background: #F9FAFB;
  border: 1px solid var(--wf-border);
  border-radius: 6px;
}

.section-tag.content-ready {
  background: var(--wf-active-bg);
  border: 1px dashed var(--wf-active-border);
}

.section-tag.content-ready svg {
  color: var(--wf-active-dot);
}


.section-tag.completed {
  background: #ECFDF5;
  border: 1px solid #A7F3D0;
}

.section-tag.completed svg {
  color: #059669;
}

.tag-num {
  font-size: 11px;
  font-weight: 700;
  color: #6B7280;
}

.section-tag.completed .tag-num {
  color: #059669;
}

.tag-title {
  font-size: 13px;
  font-weight: 500;
  color: #374151;
}

.tool-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  background: #F9FAFB;
  color: #374151;
  border: 1px solid var(--wf-border);
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
  transition: all 0.2s ease;
}

.tool-icon {
  flex-shrink: 0;
}

/* Tool Colors - Purple (Deep Insight) */
.tool-badge.tool-purple {
  background: linear-gradient(135deg, #F5F3FF 0%, #EDE9FE 100%);
  border-color: #C4B5FD;
  color: #6D28D9;
}
.tool-badge.tool-purple .tool-icon {
  stroke: #7C3AED;
}

/* Tool Colors - Blue (Panorama Search) */
.tool-badge.tool-blue {
  background: linear-gradient(135deg, #EFF6FF 0%, #DBEAFE 100%);
  border-color: #93C5FD;
  color: #1D4ED8;
}
.tool-badge.tool-blue .tool-icon {
  stroke: #2563EB;
}

/* Tool Colors - Green (Analyst Review) */
.tool-badge.tool-green {
  background: linear-gradient(135deg, #F0FDF4 0%, #DCFCE7 100%);
  border-color: #86EFAC;
  color: #15803D;
}
.tool-badge.tool-green .tool-icon {
  stroke: #16A34A;
}

/* Tool Colors - Orange (Quick Search) */
.tool-badge.tool-orange {
  background: linear-gradient(135deg, #FFF7ED 0%, #FFEDD5 100%);
  border-color: #FDBA74;
  color: #C2410C;
}
.tool-badge.tool-orange .tool-icon {
  stroke: #EA580C;
}

/* Tool Colors - Cyan (Graph Stats) */
.tool-badge.tool-cyan {
  background: linear-gradient(135deg, #ECFEFF 0%, #CFFAFE 100%);
  border-color: #67E8F9;
  color: #0E7490;
}
.tool-badge.tool-cyan .tool-icon {
  stroke: #0891B2;
}

/* Tool Colors - Pink (Entity Query) */
.tool-badge.tool-pink {
  background: linear-gradient(135deg, #FDF2F8 0%, #FCE7F3 100%);
  border-color: #F9A8D4;
  color: #BE185D;
}
.tool-badge.tool-pink .tool-icon {
  stroke: #DB2777;
}

/* Tool Colors - Gray (Default) */
.tool-badge.tool-gray {
  background: linear-gradient(135deg, #F9FAFB 0%, #F3F4F6 100%);
  border-color: #D1D5DB;
  color: #374151;
}
.tool-badge.tool-gray .tool-icon {
  stroke: #6B7280;
}

.tool-params {
  margin-top: 10px;
  background: transparent;
  border-radius: 0;
  padding: 10px 0 0 0;
  border-top: 1px dashed var(--wf-divider);
  overflow-x: auto;
}

.tool-params pre {
  margin: 0;
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  color: #4B5563;
  white-space: pre-wrap;
  word-break: break-all;
  background: #F9FAFB;
  border: 1px solid #E5E7EB;
  border-radius: 6px;
  padding: 10px;
}

/* Unified Action Buttons */
.action-btn {
  background: #F3F4F6;
  border: 1px solid #E5E7EB;
  padding: 4px 10px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 500;
  color: #6B7280;
  cursor: pointer;
  transition: all 0.15s ease;
  white-space: nowrap;
}

.action-btn:hover {
  background: #E5E7EB;
  color: #374151;
  border-color: #D1D5DB;
}

/* Result Wrapper */
.result-wrapper {
  background: transparent;
  border: none;
  border-top: 1px solid var(--wf-divider);
  border-radius: 0;
  padding: 12px 0 0 0;
}

.result-meta {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}

.result-tool {
  font-size: 12px;
  font-weight: 600;
  color: #374151;
}

.result-size {
  font-size: 10px;
  color: #6B7280;
  font-family: 'JetBrains Mono', monospace;
}

.result-raw {
  margin-top: 10px;
  max-height: 300px;
  overflow-y: auto;
}

.result-raw pre {
  margin: 0;
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  white-space: pre-wrap;
  word-break: break-word;
  color: #374151;
  background: #FFFFFF;
  border: 1px solid #E5E7EB;
  padding: 10px;
  border-radius: 6px;
}

.raw-preview {
  margin: 0;
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  white-space: pre-wrap;
  word-break: break-word;
  color: #6B7280;
}

/* Legacy toggle-raw removed - using unified .action-btn */

/* LLM Response */
.llm-meta {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.meta-tag {
  font-size: 11px;
  padding: 3px 8px;
  background: #F3F4F6;
  color: #6B7280;
  border-radius: 4px;
}

.meta-tag.active {
  background: #DBEAFE;
  color: #1E40AF;
}

.meta-tag.final-answer {
  background: #D1FAE5;
  color: #059669;
  font-weight: 600;
}

.final-answer-hint {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 10px;
  padding: 10px 14px;
  background: #ECFDF5;
  border: 1px solid #A7F3D0;
  border-radius: 6px;
  color: #065F46;
  font-size: 12px;
  font-weight: 500;
}

.final-answer-hint svg {
  flex-shrink: 0;
}

.llm-content {
  margin-top: 10px;
  max-height: 200px;
  overflow-y: auto;
}

.llm-content pre {
  margin: 0;
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  white-space: pre-wrap;
  word-break: break-word;
  color: #4B5563;
  background: #F3F4F6;
  padding: 10px;
  border-radius: 6px;
}

/* Complete Banner */
.complete-banner {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
  background: #ECFDF5;
  border: 1px solid #A7F3D0;
  border-radius: 8px;
  color: #065F46;
  font-weight: 600;
  font-size: 14px;
}

.step-nav-actions {
  display: flex;
  gap: 10px;
  margin: 4px 20px 0 20px;
}

.next-step-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  width: calc(100% - 40px);
  margin: 4px 20px 0 20px;
  padding: 14px 20px;
  font-size: 14px;
  font-weight: 600;
  color: #FFFFFF;
  background: #1F2937;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.step-nav-actions .next-step-btn {
  flex: 1;
  min-width: 0;
  width: auto;
  margin: 0;
}

.secondary-step-btn {
  color: #374151;
  background: #FFFFFF;
  border: 1px solid #D1D5DB;
}

.next-step-btn:hover {
  background: #374151;
}

.secondary-step-btn:hover {
  color: #111827;
  background: #F9FAFB;
  border-color: #9CA3AF;
}

.next-step-btn svg {
  transition: transform 0.2s ease;
}

.next-step-btn:hover svg {
  transform: translateX(4px);
}

.secondary-step-btn:hover svg {
  transform: translateX(-4px);
}

/* Workflow Empty */
.workflow-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
  color: #9CA3AF;
  font-size: 13px;
}

.empty-pulse {
  width: 24px;
  height: 24px;
  background: #E5E7EB;
  border-radius: 50%;
  margin-bottom: 16px;
  animation: pulse-ring 1.5s infinite;
}

@keyframes pulse-ring {
  0%, 100% { transform: scale(1); opacity: 1; }
  50% { transform: scale(1.2); opacity: 0.5; }
}

/* Timeline Transitions */
.timeline-item-enter-active {
  transition: all 0.4s ease;
}

.timeline-item-enter-from {
  opacity: 0;
  transform: translateX(-20px);
}

/* ========== Structured Result Display Components ========== */

/* Common Styles - using :deep() for dynamic components */
:deep(.stat-row) {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}

:deep(.stat-box) {
  flex: 1;
  background: #FFFFFF;
  border: 1px solid #E5E7EB;
  border-radius: 6px;
  padding: 10px 8px;
  text-align: center;
}

:deep(.stat-box .stat-num) {
  display: block;
  font-size: 20px;
  font-weight: 700;
  color: #111827;
  font-family: 'JetBrains Mono', monospace;
}

:deep(.stat-box .stat-label) {
  display: block;
  font-size: 10px;
  color: #9CA3AF;
  margin-top: 2px;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}

:deep(.stat-box.highlight) {
  background: #ECFDF5;
  border-color: #A7F3D0;
}

:deep(.stat-box.highlight .stat-num) {
  color: #059669;
}

:deep(.stat-box.muted) {
  background: #F9FAFB;
  border-color: #E5E7EB;
}

:deep(.stat-box.muted .stat-num) {
  color: #6B7280;
}

:deep(.query-display) {
  background: #F9FAFB;
  padding: 10px 14px;
  border-radius: 6px;
  font-size: 12px;
  color: #374151;
  margin-bottom: 12px;
  border: 1px solid #E5E7EB;
  line-height: 1.5;
}

:deep(.expand-details) {
  background: #FFFFFF;
  border: 1px solid #E5E7EB;
  padding: 8px 14px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 500;
  color: #6B7280;
  cursor: pointer;
  transition: all 0.15s ease;
}

:deep(.expand-details:hover) {
  border-color: #D1D5DB;
  color: #374151;
}

:deep(.detail-content) {
  margin-top: 14px;
  background: #FFFFFF;
  border: 1px solid #E5E7EB;
  border-radius: 8px;
  padding: 14px;
}

:deep(.section-label) {
  font-size: 11px;
  font-weight: 600;
  color: #6B7280;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin-bottom: 10px;
  padding-bottom: 6px;
  border-bottom: 1px solid #F3F4F6;
}

/* Facts Section */
:deep(.facts-section) {
  margin-bottom: 14px;
}

:deep(.fact-row) {
  display: flex;
  gap: 10px;
  padding: 8px 0;
  border-bottom: 1px solid #F3F4F6;
}

:deep(.fact-row:last-child) {
  border-bottom: none;
}

:deep(.fact-row.active) {
  background: #ECFDF5;
  margin: 0 -10px;
  padding: 8px 10px;
  border-radius: 6px;
  border-bottom: none;
}

:deep(.fact-idx) {
  min-width: 22px;
  height: 22px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #F3F4F6;
  border-radius: 6px;
  font-size: 10px;
  font-weight: 700;
  color: #6B7280;
  flex-shrink: 0;
}

:deep(.fact-row.active .fact-idx) {
  background: #A7F3D0;
  color: #065F46;
}

:deep(.fact-text) {
  font-size: 12px;
  color: #4B5563;
  line-height: 1.6;
}

/* Entities Section */
:deep(.entities-section) {
  margin-bottom: 14px;
}

:deep(.entity-chips) {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

:deep(.entity-chip) {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: #F9FAFB;
  border: 1px solid #E5E7EB;
  border-radius: 6px;
  padding: 6px 12px;
}

:deep(.chip-name) {
  font-size: 12px;
  font-weight: 500;
  color: #111827;
}

:deep(.chip-type) {
  font-size: 10px;
  color: #9CA3AF;
  background: #E5E7EB;
  padding: 1px 6px;
  border-radius: 3px;
}

/* Relations Section */
:deep(.relations-section) {
  margin-bottom: 14px;
}

:deep(.relation-row) {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 0;
  flex-wrap: wrap;
  border-bottom: 1px solid #F3F4F6;
}

:deep(.relation-row:last-child) {
  border-bottom: none;
}

:deep(.rel-node) {
  font-size: 12px;
  font-weight: 500;
  color: #111827;
  background: #F3F4F6;
  padding: 4px 10px;
  border-radius: 4px;
}

:deep(.rel-edge) {
  font-size: 10px;
  font-weight: 600;
  color: #FFFFFF;
  background: #4F46E5;
  padding: 3px 10px;
  border-radius: 10px;
}

/* ========== Interview Display - Conversation Style ========== */
:deep(.interview-display) {
  padding: 0;
}

/* Header */
:deep(.interview-display .interview-header) {
  padding: 0;
  background: transparent;
  border-bottom: none;
  margin-bottom: 16px;
}

:deep(.interview-display .header-main) {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

:deep(.interview-display .header-title) {
  font-family: 'JetBrains Mono', monospace;
  font-size: 13px;
  font-weight: 600;
  color: #111827;
  letter-spacing: -0.01em;
}

:deep(.interview-display .header-stats) {
  display: flex;
  align-items: center;
  gap: 6px;
}

:deep(.interview-display .stat-item) {
  display: flex;
  align-items: baseline;
  gap: 4px;
}

:deep(.interview-display .stat-value) {
  font-size: 14px;
  font-weight: 600;
  color: #4F46E5;
  font-family: 'JetBrains Mono', monospace;
}

:deep(.interview-display .stat-label) {
  font-size: 11px;
  color: #9CA3AF;
  text-transform: lowercase;
}

:deep(.interview-display .stat-divider) {
  color: #D1D5DB;
  font-size: 12px;
}

:deep(.interview-display .stat-size) {
  font-size: 11px;
  color: #9CA3AF;
  font-family: 'JetBrains Mono', monospace;
}

:deep(.interview-display .header-topic) {
  margin-top: 4px;
  font-size: 12px;
  color: #6B7280;
  line-height: 1.5;
}

/* Analyst Tabs - Card Style */
:deep(.interview-display .agent-tabs) {
  display: flex;
  gap: 8px;
  padding: 0 0 14px 0;
  background: transparent;
  border-bottom: 1px solid #F3F4F6;
  overflow-x: auto;
  overflow-y: hidden;
  scrollbar-width: thin;
  scrollbar-color: #E5E7EB transparent;
}

:deep(.interview-display .agent-tabs::-webkit-scrollbar) {
  height: 4px;
}

:deep(.interview-display .agent-tabs::-webkit-scrollbar-track) {
  background: transparent;
}

:deep(.interview-display .agent-tabs::-webkit-scrollbar-thumb) {
  background: #E5E7EB;
  border-radius: 2px;
}

:deep(.interview-display .agent-tabs::-webkit-scrollbar-thumb:hover) {
  background: #D1D5DB;
}

:deep(.interview-display .agent-tab) {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  background: #F9FAFB;
  border: 1px solid #E5E7EB;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 500;
  color: #6B7280;
  cursor: pointer;
  transition: all 0.15s ease;
  white-space: nowrap;
}

:deep(.interview-display .agent-tab:hover) {
  background: #F3F4F6;
  border-color: #D1D5DB;
  color: #374151;
}

:deep(.interview-display .agent-tab.active) {
  background: linear-gradient(135deg, #EEF2FF 0%, #E0E7FF 100%);
  border-color: #A5B4FC;
  color: #4338CA;
  box-shadow: 0 1px 2px rgba(99, 102, 241, 0.1);
}

:deep(.interview-display .tab-avatar) {
  width: 18px;
  height: 18px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #E5E7EB;
  color: #6B7280;
  font-size: 10px;
  font-weight: 700;
  border-radius: 50%;
  flex-shrink: 0;
}

:deep(.interview-display .agent-tab:hover .tab-avatar) {
  background: #D1D5DB;
}

:deep(.interview-display .agent-tab.active .tab-avatar) {
  background: #6366F1;
  color: #FFFFFF;
}

:deep(.interview-display .tab-name) {
  max-width: 100px;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* Interview Detail */
:deep(.interview-display .interview-detail) {
  padding: 12px 0;
  background: transparent;
}

/* Analyst Profile - No card */
:deep(.interview-display .agent-profile) {
  display: flex;
  gap: 12px;
  padding: 0;
  background: transparent;
  border: none;
  margin-bottom: 16px;
}

:deep(.interview-display .profile-avatar) {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #E5E7EB;
  color: #6B7280;
  font-size: 14px;
  font-weight: 600;
  border-radius: 50%;
  flex-shrink: 0;
}

:deep(.interview-display .profile-info) {
  flex: 1;
  min-width: 0;
}

:deep(.interview-display .profile-name) {
  font-size: 13px;
  font-weight: 600;
  color: #111827;
  margin-bottom: 2px;
}

:deep(.interview-display .profile-role) {
  font-size: 11px;
  color: #6B7280;
  margin-bottom: 4px;
}

:deep(.interview-display .profile-bio) {
  font-size: 11px;
  color: #9CA3AF;
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* Selection Reason - 选择理由 */
:deep(.interview-display .selection-reason) {
  background: #F8FAFC;
  border: 1px solid #E2E8F0;
  border-radius: 8px;
  padding: 12px 14px;
  margin-bottom: 16px;
}

:deep(.interview-display .reason-label) {
  font-size: 11px;
  font-weight: 600;
  color: #64748B;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  margin-bottom: 6px;
}

:deep(.interview-display .reason-content) {
  font-size: 12px;
  color: #475569;
  line-height: 1.6;
}

/* Q&A Thread - Clean list */
:deep(.interview-display .qa-thread) {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

:deep(.interview-display .qa-pair) {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 0;
  background: transparent;
  border: none;
  border-radius: 0;
}

:deep(.interview-display .qa-question),
:deep(.interview-display .qa-answer) {
  display: flex;
  gap: 12px;
}

:deep(.interview-display .qa-badge) {
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  font-weight: 700;
  border-radius: 4px;
  flex-shrink: 0;
}

:deep(.interview-display .q-badge) {
  background: transparent;
  color: #9CA3AF;
  border: 1px solid #E5E7EB;
}

:deep(.interview-display .a-badge) {
  background: #4F46E5;
  color: #FFFFFF;
  border: 1px solid #4F46E5;
}

:deep(.interview-display .qa-content) {
  flex: 1;
  min-width: 0;
}

:deep(.interview-display .qa-sender) {
  font-size: 11px;
  font-weight: 600;
  color: #9CA3AF;
  margin-bottom: 4px;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}

:deep(.interview-display .qa-text) {
  font-size: 13px;
  color: #374151;
  line-height: 1.6;
}

:deep(.interview-display .qa-answer) {
  background: transparent;
  padding: 0;
  border: none;
  margin-top: 0;
}

:deep(.interview-display .answer-placeholder) {
  opacity: 0.6;
}

:deep(.interview-display .placeholder-text) {
  font-style: italic;
  color: #9CA3AF;
}

:deep(.interview-display .qa-answer-header) {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
}

/* Platform Switch */
:deep(.interview-display .platform-switch) {
  display: flex;
  gap: 2px;
  background: transparent;
  padding: 0;
  border-radius: 0;
}

:deep(.interview-display .platform-btn) {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 2px 6px;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 500;
  color: #9CA3AF;
  cursor: pointer;
  transition: all 0.15s ease;
}

:deep(.interview-display .platform-btn:hover) {
  color: #6B7280;
}

:deep(.interview-display .platform-btn.active) {
  background: transparent;
  color: #4F46E5;
  border-color: #E5E7EB;
  box-shadow: none;
}

:deep(.interview-display .platform-icon) {
  flex-shrink: 0;
}

:deep(.interview-display .answer-text) {
  font-size: 13px;
  color: #111827;
  line-height: 1.6;
}

:deep(.interview-display .answer-text strong) {
  color: #111827;
  font-weight: 600;
}

:deep(.interview-display .expand-answer-btn) {
  display: inline-block;
  margin-top: 8px;
  padding: 0;
  background: transparent;
  border: none;
  border-bottom: 1px dotted #D1D5DB;
  border-radius: 0;
  font-size: 11px;
  font-weight: 500;
  color: #9CA3AF;
  cursor: pointer;
  transition: all 0.15s ease;
}

:deep(.interview-display .expand-answer-btn:hover) {
  background: transparent;
  color: #6B7280;
  border-bottom-style: solid;
}

/* Quotes Section - Clean list */
:deep(.interview-display .quotes-section) {
  background: transparent;
  border: none;
  border-top: 1px solid #F3F4F6;
  border-radius: 0;
  padding: 16px 0 0 0;
  margin-top: 16px;
}

:deep(.interview-display .quotes-header) {
  font-size: 11px;
  font-weight: 600;
  color: #9CA3AF;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin-bottom: 12px;
}

:deep(.interview-display .quotes-list) {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

:deep(.interview-display .quote-item) {
  margin: 0;
  padding: 10px 12px;
  background: #FFFFFF;
  border: 1px solid #E5E7EB;
  border-radius: 6px;
  font-size: 12px;
  font-style: italic;
  color: #4B5563;
  line-height: 1.5;
}

/* Summary Section */
:deep(.interview-display .summary-section) {
  margin-top: 20px;
  padding: 16px 0 0 0;
  background: transparent;
  border: none;
  border-top: 1px solid #F3F4F6;
  border-radius: 0;
}

:deep(.interview-display .summary-header) {
  font-size: 11px;
  font-weight: 600;
  color: #9CA3AF;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin-bottom: 8px;
}

:deep(.interview-display .summary-content) {
  font-size: 13px;
  color: #374151;
  line-height: 1.6;
}

/* Markdown styles in summary */
:deep(.interview-display .summary-content h2),
:deep(.interview-display .summary-content h3),
:deep(.interview-display .summary-content h4),
:deep(.interview-display .summary-content h5) {
  margin: 12px 0 8px 0;
  font-weight: 600;
  color: #111827;
}

:deep(.interview-display .summary-content h2) {
  font-size: 15px;
}

:deep(.interview-display .summary-content h3) {
  font-size: 14px;
}

:deep(.interview-display .summary-content h4),
:deep(.interview-display .summary-content h5) {
  font-size: 13px;
}

:deep(.interview-display .summary-content p) {
  margin: 8px 0;
}

:deep(.interview-display .summary-content strong) {
  font-weight: 600;
  color: #111827;
}

:deep(.interview-display .summary-content em) {
  font-style: italic;
}

:deep(.interview-display .summary-content ul),
:deep(.interview-display .summary-content ol) {
  margin: 8px 0;
  padding-left: 20px;
}

:deep(.interview-display .summary-content li) {
  margin: 4px 0;
}

:deep(.interview-display .summary-content blockquote) {
  margin: 8px 0;
  padding-left: 12px;
  border-left: 3px solid #E5E7EB;
  color: #6B7280;
  font-style: italic;
}

/* Markdown styles in quotes */
:deep(.interview-display .quote-item strong) {
  font-weight: 600;
  color: #374151;
}

:deep(.interview-display .quote-item em) {
  font-style: italic;
}

/* ========== Enhanced Insight Display Styles ========== */
:deep(.insight-display) {
  padding: 0;
}

:deep(.insight-header) {
  padding: 12px 16px;
  background: linear-gradient(135deg, #F5F3FF 0%, #EDE9FE 100%);
  border-radius: 8px 8px 0 0;
  border: 1px solid #C4B5FD;
  border-bottom: none;
}

:deep(.insight-header .header-main) {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

:deep(.insight-header .header-title) {
  font-size: 14px;
  font-weight: 700;
  color: #6D28D9;
}

:deep(.insight-header .header-stats) {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
}

:deep(.insight-header .stat-item) {
  display: flex;
  align-items: baseline;
  gap: 2px;
}

:deep(.insight-header .stat-value) {
  font-family: 'JetBrains Mono', monospace;
  font-weight: 700;
  color: #7C3AED;
}

:deep(.insight-header .stat-label) {
  color: #8B5CF6;
  font-size: 10px;
}

:deep(.insight-header .stat-divider) {
  color: #C4B5FD;
  margin: 0 4px;
}

:deep(.insight-header .stat-size) {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  color: #9CA3AF;
}

:deep(.insight-header .header-topic) {
  font-size: 13px;
  color: #5B21B6;
  line-height: 1.5;
}

:deep(.insight-header .header-scenario) {
  margin-top: 6px;
  font-size: 11px;
  color: #7C3AED;
}

:deep(.insight-header .scenario-label) {
  font-weight: 600;
}

:deep(.insight-tabs) {
  display: flex;
  gap: 2px;
  padding: 8px 12px;
  background: #FAFAFA;
  border: 1px solid #E5E7EB;
  border-top: none;
}

:deep(.insight-tab) {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 6px 10px;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 500;
  color: #6B7280;
  cursor: pointer;
  transition: all 0.15s ease;
}

:deep(.insight-tab:hover) {
  background: #F3F4F6;
  color: #374151;
}

:deep(.insight-tab.active) {
  background: #FFFFFF;
  color: #7C3AED;
  border-color: #C4B5FD;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
}


:deep(.insight-content) {
  padding: 12px;
  background: #FFFFFF;
  border: 1px solid #E5E7EB;
  border-top: none;
  border-radius: 0 0 8px 8px;
}

:deep(.insight-display .panel-header) {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid #F3F4F6;
}

:deep(.insight-display .panel-title) {
  font-size: 12px;
  font-weight: 600;
  color: #374151;
}

:deep(.insight-display .panel-count) {
  font-size: 10px;
  color: #9CA3AF;
}

:deep(.insight-display .facts-list),
:deep(.insight-display .relations-list),
:deep(.insight-display .subqueries-list) {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

:deep(.insight-display .entities-grid) {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

:deep(.insight-display .fact-item) {
  display: flex;
  gap: 10px;
  padding: 10px 12px;
  background: #F9FAFB;
  border: 1px solid #E5E7EB;
  border-radius: 6px;
}

:deep(.insight-display .fact-number) {
  flex-shrink: 0;
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #E5E7EB;
  border-radius: 50%;
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  font-weight: 700;
  color: #6B7280;
}

:deep(.insight-display .fact-content) {
  flex: 1;
  font-size: 12px;
  color: #374151;
  line-height: 1.6;
}

/* Entity Tag Styles - Compact multi-column layout */
:deep(.insight-display .entity-tag) {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  background: #F9FAFB;
  border: 1px solid #E5E7EB;
  border-radius: 6px;
  cursor: default;
  transition: all 0.15s ease;
}

:deep(.insight-display .entity-tag:hover) {
  background: #F3F4F6;
  border-color: #D1D5DB;
}

:deep(.insight-display .entity-tag .entity-name) {
  font-size: 12px;
  font-weight: 500;
  color: #111827;
}

:deep(.insight-display .entity-tag .entity-type) {
  font-size: 9px;
  color: #7C3AED;
  background: #EDE9FE;
  padding: 1px 4px;
  border-radius: 3px;
}

:deep(.insight-display .entity-tag .entity-fact-count) {
  font-size: 9px;
  color: #9CA3AF;
  margin-left: 2px;
}

/* Legacy entity card styles for backwards compatibility */
:deep(.insight-display .entity-card) {
  padding: 12px;
  background: #F9FAFB;
  border: 1px solid #E5E7EB;
  border-radius: 8px;
}

:deep(.insight-display .entity-header) {
  display: flex;
  align-items: center;
  gap: 10px;
}

:deep(.insight-display .entity-info) {
  flex: 1;
}

:deep(.insight-display .entity-card .entity-name) {
  font-size: 13px;
  font-weight: 600;
  color: #111827;
}

:deep(.insight-display .entity-card .entity-type) {
  font-size: 10px;
  color: #7C3AED;
  background: #EDE9FE;
  padding: 2px 6px;
  border-radius: 4px;
  display: inline-block;
  margin-top: 2px;
}

:deep(.insight-display .entity-card .entity-fact-count) {
  font-size: 10px;
  color: #9CA3AF;
  background: #F3F4F6;
  padding: 2px 6px;
  border-radius: 4px;
}

:deep(.insight-display .entity-summary) {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid #E5E7EB;
  font-size: 11px;
  color: #6B7280;
  line-height: 1.5;
}

/* Relation Item Styles */
:deep(.insight-display .relation-item) {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  background: #F9FAFB;
  border: 1px solid #E5E7EB;
  border-radius: 6px;
}

:deep(.insight-display .rel-source),
:deep(.insight-display .rel-target) {
  padding: 4px 8px;
  background: #FFFFFF;
  border: 1px solid #D1D5DB;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 500;
  color: #374151;
}

:deep(.insight-display .rel-arrow) {
  display: flex;
  align-items: center;
  gap: 4px;
  flex: 1;
}

:deep(.insight-display .rel-line) {
  flex: 1;
  height: 1px;
  background: #D1D5DB;
}

:deep(.insight-display .rel-label) {
  padding: 2px 6px;
  background: #EDE9FE;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 500;
  color: #7C3AED;
  white-space: nowrap;
}

/* Sub-query Styles */
:deep(.insight-display .subquery-item) {
  display: flex;
  gap: 10px;
  padding: 10px 12px;
  background: #F9FAFB;
  border: 1px solid #E5E7EB;
  border-radius: 6px;
}

:deep(.insight-display .subquery-number) {
  flex-shrink: 0;
  padding: 2px 6px;
  background: #7C3AED;
  border-radius: 4px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  font-weight: 700;
  color: #FFFFFF;
}

:deep(.insight-display .subquery-text) {
  font-size: 12px;
  color: #374151;
  line-height: 1.5;
}

/* Expand Button */
:deep(.insight-display .expand-btn),
:deep(.panorama-display .expand-btn),
:deep(.quick-search-display .expand-btn) {
  display: block;
  width: 100%;
  margin-top: 12px;
  padding: 8px 12px;
  background: #F9FAFB;
  border: 1px solid #E5E7EB;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 500;
  color: #6B7280;
  cursor: pointer;
  transition: all 0.15s ease;
  text-align: center;
}

:deep(.insight-display .expand-btn:hover),
:deep(.panorama-display .expand-btn:hover),
:deep(.quick-search-display .expand-btn:hover) {
  background: #F3F4F6;
  color: #374151;
  border-color: #D1D5DB;
}

/* Empty State */
:deep(.insight-display .empty-state),
:deep(.panorama-display .empty-state),
:deep(.quick-search-display .empty-state) {
  padding: 24px;
  text-align: center;
  font-size: 12px;
  color: #9CA3AF;
}

/* ========== Enhanced Panorama Display Styles ========== */
:deep(.panorama-display) {
  padding: 0;
}

:deep(.panorama-header) {
  padding: 12px 16px;
  background: linear-gradient(135deg, #EFF6FF 0%, #DBEAFE 100%);
  border-radius: 8px 8px 0 0;
  border: 1px solid #93C5FD;
  border-bottom: none;
}

:deep(.panorama-header .header-main) {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

:deep(.panorama-header .header-title) {
  font-size: 14px;
  font-weight: 700;
  color: #1D4ED8;
}

:deep(.panorama-header .header-stats) {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
}

:deep(.panorama-header .stat-item) {
  display: flex;
  align-items: baseline;
  gap: 2px;
}

:deep(.panorama-header .stat-value) {
  font-family: 'JetBrains Mono', monospace;
  font-weight: 700;
  color: #2563EB;
}

:deep(.panorama-header .stat-label) {
  color: #60A5FA;
  font-size: 10px;
}

:deep(.panorama-header .stat-divider) {
  color: #93C5FD;
  margin: 0 4px;
}

:deep(.panorama-header .stat-size) {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  color: #9CA3AF;
}

:deep(.panorama-header .header-topic) {
  font-size: 13px;
  color: #1E40AF;
  line-height: 1.5;
}

:deep(.panorama-tabs) {
  display: flex;
  gap: 2px;
  padding: 8px 12px;
  background: #FAFAFA;
  border: 1px solid #E5E7EB;
  border-top: none;
}

:deep(.panorama-tab) {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 6px 10px;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 500;
  color: #6B7280;
  cursor: pointer;
  transition: all 0.15s ease;
}

:deep(.panorama-tab:hover) {
  background: #F3F4F6;
  color: #374151;
}

:deep(.panorama-tab.active) {
  background: #FFFFFF;
  color: #2563EB;
  border-color: #93C5FD;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
}


:deep(.panorama-content) {
  padding: 12px;
  background: #FFFFFF;
  border: 1px solid #E5E7EB;
  border-top: none;
  border-radius: 0 0 8px 8px;
}

:deep(.panorama-display .panel-header) {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid #F3F4F6;
}

:deep(.panorama-display .panel-title) {
  font-size: 12px;
  font-weight: 600;
  color: #374151;
}

:deep(.panorama-display .panel-count) {
  font-size: 10px;
  color: #9CA3AF;
}

:deep(.panorama-display .facts-list) {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

:deep(.panorama-display .fact-item) {
  display: flex;
  gap: 10px;
  padding: 10px 12px;
  background: #F9FAFB;
  border: 1px solid #E5E7EB;
  border-radius: 6px;
}

:deep(.panorama-display .fact-item.active) {
  background: #F9FAFB;
  border-color: #E5E7EB;
}

:deep(.panorama-display .fact-item.historical) {
  background: #F9FAFB;
  border-color: #E5E7EB;
}

:deep(.panorama-display .fact-number) {
  flex-shrink: 0;
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #E5E7EB;
  border-radius: 50%;
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  font-weight: 700;
  color: #6B7280;
}

:deep(.panorama-display .fact-item.active .fact-number) {
  background: #E5E7EB;
  color: #6B7280;
}

:deep(.panorama-display .fact-item.historical .fact-number) {
  background: #9CA3AF;
  color: #FFFFFF;
}

:deep(.panorama-display .fact-content) {
  flex: 1;
  font-size: 12px;
  color: #374151;
  line-height: 1.6;
}

:deep(.panorama-display .fact-time) {
  display: block;
  font-size: 10px;
  color: #9CA3AF;
  margin-bottom: 4px;
  font-family: 'JetBrains Mono', monospace;
}

:deep(.panorama-display .fact-text) {
  display: block;
}

/* Entities Grid */
:deep(.panorama-display .entities-grid) {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

:deep(.panorama-display .entity-tag) {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  background: #F9FAFB;
  border: 1px solid #E5E7EB;
  border-radius: 6px;
}

:deep(.panorama-display .entity-name) {
  font-size: 12px;
  font-weight: 500;
  color: #374151;
}

:deep(.panorama-display .entity-type) {
  font-size: 10px;
  color: #2563EB;
  background: #DBEAFE;
  padding: 2px 6px;
  border-radius: 4px;
}

/* ========== Enhanced Quick Search Display Styles ========== */
:deep(.quick-search-display) {
  padding: 0;
}

:deep(.quicksearch-header) {
  padding: 12px 16px;
  background: linear-gradient(135deg, #FFF7ED 0%, #FFEDD5 100%);
  border-radius: 8px 8px 0 0;
  border: 1px solid #FDBA74;
  border-bottom: none;
}

:deep(.quicksearch-header .header-main) {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

:deep(.quicksearch-header .header-title) {
  font-size: 14px;
  font-weight: 700;
  color: #C2410C;
}

:deep(.quicksearch-header .header-stats) {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
}

:deep(.quicksearch-header .stat-item) {
  display: flex;
  align-items: baseline;
  gap: 2px;
}

:deep(.quicksearch-header .stat-value) {
  font-family: 'JetBrains Mono', monospace;
  font-weight: 700;
  color: #EA580C;
}

:deep(.quicksearch-header .stat-label) {
  color: #FB923C;
  font-size: 10px;
}

:deep(.quicksearch-header .stat-divider) {
  color: #FDBA74;
  margin: 0 4px;
}

:deep(.quicksearch-header .stat-size) {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  color: #9CA3AF;
}

:deep(.quicksearch-header .header-query) {
  font-size: 13px;
  color: #9A3412;
  line-height: 1.5;
}

:deep(.quicksearch-header .query-label) {
  font-weight: 600;
}

:deep(.quicksearch-tabs) {
  display: flex;
  gap: 2px;
  padding: 8px 12px;
  background: #FAFAFA;
  border: 1px solid #E5E7EB;
  border-top: none;
}

:deep(.quicksearch-tab) {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 6px 10px;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 500;
  color: #6B7280;
  cursor: pointer;
  transition: all 0.15s ease;
}

:deep(.quicksearch-tab:hover) {
  background: #F3F4F6;
  color: #374151;
}

:deep(.quicksearch-tab.active) {
  background: #FFFFFF;
  color: #EA580C;
  border-color: #FDBA74;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
}


:deep(.quicksearch-content) {
  padding: 12px;
  background: #FFFFFF;
  border: 1px solid #E5E7EB;
  border-top: none;
  border-radius: 0 0 8px 8px;
}

/* When there are no tabs, content connects directly to header */
:deep(.quicksearch-content.no-tabs) {
  border-top: none;
}

:deep(.quick-search-display .panel-header) {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid #F3F4F6;
}

:deep(.quick-search-display .panel-title) {
  font-size: 12px;
  font-weight: 600;
  color: #374151;
}

:deep(.quick-search-display .panel-count) {
  font-size: 10px;
  color: #9CA3AF;
}

:deep(.quick-search-display .facts-list) {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

:deep(.quick-search-display .fact-item) {
  display: flex;
  gap: 10px;
  padding: 10px 12px;
  background: #F9FAFB;
  border: 1px solid #E5E7EB;
  border-radius: 6px;
}

:deep(.quick-search-display .fact-item.active) {
  background: #F9FAFB;
  border-color: #E5E7EB;
}

:deep(.quick-search-display .fact-number) {
  flex-shrink: 0;
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #E5E7EB;
  border-radius: 50%;
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  font-weight: 700;
  color: #6B7280;
}

:deep(.quick-search-display .fact-item.active .fact-number) {
  background: #E5E7EB;
  color: #6B7280;
}

:deep(.quick-search-display .fact-content) {
  flex: 1;
  font-size: 12px;
  color: #374151;
  line-height: 1.6;
}

/* Edges Panel */
:deep(.quick-search-display .edges-list) {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

:deep(.quick-search-display .edge-item) {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  background: #F9FAFB;
  border: 1px solid #E5E7EB;
  border-radius: 6px;
}

:deep(.quick-search-display .edge-source),
:deep(.quick-search-display .edge-target) {
  padding: 4px 8px;
  background: #FFFFFF;
  border: 1px solid #D1D5DB;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 500;
  color: #374151;
}

:deep(.quick-search-display .edge-arrow) {
  display: flex;
  align-items: center;
  gap: 4px;
  flex: 1;
}

:deep(.quick-search-display .edge-line) {
  flex: 1;
  height: 1px;
  background: #D1D5DB;
}

:deep(.quick-search-display .edge-label) {
  padding: 2px 6px;
  background: #FFEDD5;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 500;
  color: #C2410C;
  white-space: nowrap;
}

/* Nodes Grid */
:deep(.quick-search-display .nodes-grid) {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

:deep(.quick-search-display .node-tag) {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  background: #F9FAFB;
  border: 1px solid #E5E7EB;
  border-radius: 6px;
}

:deep(.quick-search-display .node-name) {
  font-size: 12px;
  font-weight: 500;
  color: #374151;
}

:deep(.quick-search-display .node-type) {
  font-size: 10px;
  color: #EA580C;
  background: #FFEDD5;
  padding: 2px 6px;
  border-radius: 4px;
}

/* Console Logs - 与 Step3Simulation.vue 保持一致 */
.console-logs {
  background: #000;
  color: #DDD;
  padding: 16px;
  font-family: 'JetBrains Mono', monospace;
  border-top: 1px solid #222;
  flex-shrink: 0;
}

.log-header {
  display: flex;
  justify-content: space-between;
  border-bottom: 1px solid #333;
  padding-bottom: 8px;
  margin-bottom: 8px;
  font-size: 10px;
  color: #666;
}

.log-title {
  text-transform: uppercase;
  letter-spacing: 0.1em;
}

.log-content {
  display: flex;
  flex-direction: column;
  gap: 4px;
  height: 100px;
  overflow-y: auto;
  padding-right: 4px;
}

.log-content::-webkit-scrollbar { width: 4px; }
.log-content::-webkit-scrollbar-thumb { background: #333; border-radius: 2px; }

.log-line {
  font-size: 11px;
  line-height: 1.5;
}

.log-msg {
  color: #BBB;
  word-break: break-all;
}

.log-msg.error { color: #EF5350; }
.log-msg.warning { color: #FFA726; }
.log-msg.success { color: #66BB6A; }
</style>

<style>
/* English locale: smaller report title */
html[lang="en"] .report-header-block .main-title {
  font-size: 28px;
}
</style>
