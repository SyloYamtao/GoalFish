import { regenerateProjectStep } from '../api/projectWorkflow'

const STEP_IMPACT = {
  1: '重新生成 Step1 会使当前 Step2 配置、Step3 场景推演、Step4 报告和 Step5 问答失效。旧结果会保留在历史记录中，但不再作为当前项目结果。是否继续？',
  2: '重新生成 Step2 会使当前 Step3 场景推演、Step4 报告和 Step5 问答失效。旧结果会保留在历史记录中，但不再作为当前项目结果。是否继续？',
  3: '重新生成 Step3 会使当前 Step4 报告和 Step5 问答失效。旧结果会保留在历史记录中，但不再作为当前项目结果。是否继续？',
  4: '重新生成 Step4 会使当前 Step5 问答失效。旧结果会保留在历史记录中，但不再作为当前项目结果。是否继续？',
  5: '重新生成 Step5 会清空当前活跃问答会话。旧问答会保留在历史记录中，但不再作为当前项目结果。是否继续？',
}

export const regenerateStepWithConfirm = async ({
  projectId,
  step,
  reason = 'user_requested',
  confirmMessage,
  onBefore,
  onAfter,
}) => {
  if (!projectId || !step) return null
  const message = confirmMessage || STEP_IMPACT[step] || '重新生成会使当前步骤及下游结果失效。是否继续？'
  if (!window.confirm(message)) return null
  onBefore?.()
  const response = await regenerateProjectStep(projectId, step, {
    reason,
    preserve_history: true,
  })
  onAfter?.(response.data || response)
  return response.data || response
}
