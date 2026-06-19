export const reportOutlineFromSnapshot = (report = {}) => {
  const metadataOutline = report?.metadata?.outline || report?.report_metadata?.outline
  const outline = report?.outline || metadataOutline
  if (outline?.sections?.length) return outline

  const title = report?.title || report?.match_name || 'Prediction Report'
  const summary = report?.summary || ''
  const sections = (report?.sections || []).map(section => ({
    title: section.title || `Section ${section.section_index || ''}`.trim(),
    content: ''
  }))

  return sections.length ? { title, summary, sections } : null
}

export const generatedSectionsFromSnapshot = (sections = []) => (
  (sections || []).reduce((acc, section) => {
    if (!section?.section_index) return acc
    acc[section.section_index] = section.content || ''
    return acc
  }, {})
)
