import service, { requestWithRetry } from './index'

/**
 * 获取 Agent 日志（增量）
 * @param {string} reportId
 * @param {number} fromLine - 从第几行开始获取
 */
export const getAgentLog = (reportId, fromLine = 0, params = {}) => {
  return service.get(`/api/report/${reportId}/agent-log`, { params: { from_line: fromLine, ...params } })
}

/**
 * 获取控制台日志（增量）
 * @param {string} reportId
 * @param {number} fromLine - 从第几行开始获取
 */
export const getConsoleLog = (reportId, fromLine = 0) => {
  return service.get(`/api/report/${reportId}/console-log`, { params: { from_line: fromLine } })
}

/**
 * 获取报告详情
 * @param {string} reportId
 */
export const getReport = (reportId, params = {}) => {
  return service.get(`/api/report/${reportId}`, { params })
}

/**
 * 获取报告已生成章节
 * @param {string} reportId
 */
export const getReportSections = (reportId, params = {}) => {
  return service.get(`/api/report/${reportId}/sections`, { params })
}

/**
 * 获取或创建报告对话
 * @param {string} reportId
 * @param {Object} data - { target_type?, target_agent_id?, title?, metadata? }
 */
export const createReportConversation = (reportId, data = {}) => {
  return service.post(`/api/report/${reportId}/conversations`, data)
}

/**
 * 获取报告对话消息
 * @param {string} reportId
 * @param {string} conversationId
 * @param {Object} params - { limit? }
 */
export const getReportConversationMessages = (reportId, conversationId, params = {}) => {
  return service.get(`/api/report/${reportId}/conversations/${conversationId}/messages`, { params })
}

/**
 * 发送报告对话消息并持久化
 * @param {string} reportId
 * @param {string} conversationId
 * @param {Object} data - { message }
 */
export const sendReportConversationMessage = (reportId, conversationId, data) => {
  return requestWithRetry(
    () => service.post(`/api/report/${reportId}/conversations/${conversationId}/messages`, data),
    3,
    1000
  )
}
