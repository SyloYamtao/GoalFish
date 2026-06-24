import { regenerateProjectStep } from '../api/projectWorkflow'

const STEP_IMPACT = {
  1: 'Regenerating Step 1 will invalidate the current Step 2 config, Step 3 simulation, Step 4 report, and Step 5 Q&A. Historical results are kept, but they will no longer be the current project result. Continue?',
  2: 'Regenerating Step 2 will invalidate the current Step 3 simulation, Step 4 report, and Step 5 Q&A. Historical results are kept, but they will no longer be the current project result. Continue?',
  3: 'Regenerating Step 3 will invalidate the current Step 4 report and Step 5 Q&A. Historical results are kept, but they will no longer be the current project result. Continue?',
  4: 'Regenerating Step 4 will invalidate the current Step 5 Q&A. Historical results are kept, but they will no longer be the current project result. Continue?',
  5: 'Regenerating Step 5 will clear the current active Q&A session. Historical Q&A is kept, but it will no longer be the current project result. Continue?',
}

const DEFAULT_IMPACT = 'Regenerating will invalidate this step and downstream results. Continue?'

export const regenerateStepWithConfirm = async ({
  projectId,
  step,
  reason = 'user_requested',
  confirmMessage,
  t,
  onBefore,
  onAfter,
}) => {
  if (!projectId || !step) return null
  const key = `workflow.stepImpact${step}`
  const message = confirmMessage || translate(t, key, STEP_IMPACT[step] || DEFAULT_IMPACT)
  if (!window.confirm(message)) return null
  onBefore?.()
  const response = await regenerateProjectStep(projectId, step, {
    reason,
    preserve_history: true,
  })
  onAfter?.(response.data || response)
  return response.data || response
}

function translate(t, key, fallback) {
  if (typeof t !== 'function') return fallback
  const translated = t(key)
  return translated && translated !== key ? translated : fallback
}
