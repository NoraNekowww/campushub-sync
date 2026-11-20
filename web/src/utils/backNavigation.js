import { onBeforeUnmount, watch } from 'vue'

const backStack = []
let handlerSeq = 0
let fallbackHandler = null

/** Register a fallback handler invoked when no active modal/card handler is stacked. */
export function setBackFallback(fn) {
  fallbackHandler = typeof fn === 'function' ? fn : null
}

/** Push (or promote) a back handler on top of the LIFO stack. */
export function pushBackHandler(id, closeFn) {
  removeBackHandler(id)
  backStack.push({ id, closeFn })
}

/** Remove a back handler from the stack when its overlay closes/unmounts. */
export function removeBackHandler(id) {
  for (let i = backStack.length - 1; i >= 0; i--) {
    if (backStack[i].id === id) backStack.splice(i, 1)
  }
}

/** Handle Android system back gesture / Escape: returns true if an overlay/view consumed it. */
export function dispatchAppBack() {
  while (backStack.length > 0) {
    const top = backStack.pop()
    if (top && typeof top.closeFn === 'function') {
      top.closeFn()
      return true
    }
  }
  if (typeof fallbackHandler === 'function' && fallbackHandler()) {
    return true
  }
  return false
}

/** Bind a reactive overlay/card boolean (or getter) to the LIFO Android back stack. */
export function useBackHandler(source, closeFn) {
  const id = `back_${++handlerSeq}`
  watch(
    source,
    (active) => {
      if (active) pushBackHandler(id, closeFn)
      else removeBackHandler(id)
    },
    { immediate: true },
  )
  onBeforeUnmount(() => removeBackHandler(id))
}

if (typeof window !== 'undefined') {
  window.__campushubHandleBack = dispatchAppBack
}
