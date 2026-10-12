import { ref } from 'vue'

export function useForm() {
  const submitting = ref(false)

  async function submit<T>(handler: () => Promise<T>) {
    submitting.value = true
    try {
      return await handler()
    } finally {
      submitting.value = false
    }
  }

  return {
    submitting,
    submit
  }
}
