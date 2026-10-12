import type { FormItemRule } from 'element-plus'

export const rules = {
  required(label: string, trigger: 'blur' | 'change' = 'blur'): FormItemRule {
    return { required: true, message: `${label}不能为空`, trigger }
  },
  email(): FormItemRule {
    return {
      type: 'email',
      message: '请输入正确的邮箱格式',
      trigger: ['blur', 'change']
    }
  },
  phone(): FormItemRule {
    return {
      pattern: /^(\+?\d[\d-]{6,20})$/,
      message: '请输入正确的联系电话',
      trigger: ['blur', 'change']
    }
  },
  versionNo(): FormItemRule {
    return {
      pattern: /^[A-Z0-9-]{1,10}$/,
      message: '版本号仅支持大写字母、数字和中划线',
      trigger: ['blur', 'change']
    }
  }
}
