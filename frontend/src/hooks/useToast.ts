import { useCallback, useState } from 'react'

export function useToast() {
  const [toast, setToast] = useState<string | null>(null)

  const show = useCallback((msg: string) => {
    setToast(msg)
    window.setTimeout(() => setToast(null), 2800)
  }, [])

  return { toast, show }
}
