import service from './index'

export const getProjectWorkflow = (projectId) => {
  return service.get(`/api/projects/${projectId}/workflow`)
}

export const regenerateProjectStep = (projectId, step, data = {}) => {
  return service.post(`/api/projects/${projectId}/steps/${step}/regenerate`, {
    reason: data.reason || 'user_requested',
    preserve_history: data.preserve_history !== false,
  })
}
