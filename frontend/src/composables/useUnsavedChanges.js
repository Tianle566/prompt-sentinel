import { onBeforeUnmount, onMounted, unref } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { ElMessageBox } from 'element-plus'

export function useUnsavedChanges(dirty) {
  const beforeUnload = (event) => {
    if (!unref(dirty)) return
    event.preventDefault()
    event.returnValue = ''
  }
  onMounted(() => window.addEventListener('beforeunload', beforeUnload))
  onBeforeUnmount(() => window.removeEventListener('beforeunload', beforeUnload))
  onBeforeRouteLeave(async (to) => {
    if (to.meta.public) return true
    if (!unref(dirty)) return true
    try {
      await ElMessageBox.confirm('更改尚未保存，离开后将丢失。', '离开此页？', {
        confirmButtonText: '离开',
        cancelButtonText: '继续编辑',
        type: 'warning',
      })
      return true
    } catch {
      return false
    }
  })
}
