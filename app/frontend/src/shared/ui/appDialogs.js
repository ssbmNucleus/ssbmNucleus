let dialogHandler = null

export function setAppDialogHandler(handler) {
  dialogHandler = handler
  return () => {
    if (dialogHandler === handler) {
      dialogHandler = null
    }
  }
}

function requestDialog(options) {
  if (!dialogHandler) {
    if (options.type === 'confirm') return Promise.resolve(false)
    if (options.type === 'prompt') return Promise.resolve(null)
    return Promise.resolve()
  }
  return dialogHandler(options)
}

export function appAlert(message, options = {}) {
  return requestDialog({
    type: 'alert',
    title: options.title || 'Notice',
    message: String(message ?? ''),
    confirmText: options.confirmText || 'OK',
    confirmStyle: options.confirmStyle || 'primary',
  })
}

export function appConfirm(message, options = {}) {
  return requestDialog({
    type: 'confirm',
    title: options.title || 'Confirm',
    message: String(message ?? ''),
    confirmText: options.confirmText || 'Confirm',
    cancelText: options.cancelText || 'Cancel',
    confirmStyle: options.confirmStyle || 'danger',
  })
}

export function appPrompt(message, options = {}) {
  return requestDialog({
    type: 'prompt',
    title: options.title || 'Input',
    message: String(message ?? ''),
    defaultValue: options.defaultValue || '',
    placeholder: options.placeholder || '',
    confirmText: options.confirmText || 'Save',
    cancelText: options.cancelText || 'Cancel',
  })
}
