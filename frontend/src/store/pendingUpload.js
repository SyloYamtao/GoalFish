/**
 * 临时存储待上传的赛事资料和预测需求。
 * 首页点击启动后立即跳转，在 Process 页面再进行 API 调用。
 */
import { reactive } from 'vue'

export const DEFAULT_PREDICTION_REQUIREMENT = 'Predict this match process and result rigorously'

const state = reactive({
  files: [],
  predictionRequirement: '',
  isPending: false
})

export function setPendingPredictionUpload(files, requirement = DEFAULT_PREDICTION_REQUIREMENT) {
  state.files = files
  const normalizedRequirement = typeof requirement === 'string' ? requirement.trim() : ''
  state.predictionRequirement = normalizedRequirement || DEFAULT_PREDICTION_REQUIREMENT
  state.isPending = true
}

export function getPendingPredictionUpload() {
  return {
    files: state.files,
    predictionRequirement: state.predictionRequirement,
    isPending: state.isPending
  }
}

export function clearPendingPredictionUpload() {
  state.files = []
  state.predictionRequirement = ''
  state.isPending = false
}

export default state
