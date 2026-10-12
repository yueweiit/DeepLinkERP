import { ElMessageBox } from 'element-plus'

export function useConfirm() {
  function confirm(message: string, title = '请确认') {
    return ElMessageBox.confirm(message, title, {
      type: 'warning',
      confirmButtonText: '确认',
      cancelButtonText: '取消'
    })
  }

  return { confirm }
}
